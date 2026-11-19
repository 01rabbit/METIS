import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from metis.evaluation.issue6_build_preflight import NATIVE_SHA256
from metis.evaluation.issue6_live_grant_policy import (
    LEDGER_SCHEMA,
    LiveCalibrationGrant,
    LiveCalibrationPlan,
    LiveGrantReview,
)
from metis.evaluation.issue6_pilot_admission import DryRunApproval, FrozenCase

DIGEST = "a" * 64
GENERATION = "f" * 64


def provision(directory, generation=GENERATION):
    database = directory / "issue6-live-reviews.sqlite"
    database.touch(mode=0o600, exist_ok=False)
    with closing(sqlite3.connect(database)) as db, db:
        for statement in LEDGER_SCHEMA:
            db.execute(statement)
        db.execute("INSERT INTO offline_live_ledger_identity VALUES (1, ?)", (generation,))
    return database


def review_count(directory):
    with closing(sqlite3.connect(directory / "issue6-live-reviews.sqlite")) as db:
        return db.execute("SELECT COUNT(*) FROM offline_live_grant_reviews").fetchone()[0]


@pytest.fixture
def live(tmp_path):
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    directory = tmp_path / "operator-state"
    directory.mkdir(mode=0o700)
    provision(directory)
    reviewer = LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 100)
    plan = LiveCalibrationPlan(
        source_sha256=DIGEST, protocol_sha256=DIGEST, native_sha256=NATIVE_SHA256, runtime_version="0.169.0",
        model="gpt-6.1-sol", effort="low", account_binding=DIGEST, workspace_binding=DIGEST,
        phase_schema_sha256=(DIGEST, "b" * 64),
        cases=tuple(FrozenCase(case_id=f"opaque-{i}", artifact_hmac=f"{i:064x}") for i in range(36)),
    )
    grant = LiveCalibrationGrant(
        grant_id="a" * 32, mode="live_calibration", ledger_binding=reviewer.ledger_binding,
        ledger_generation=reviewer.ledger_generation, plan=plan, issued_at=90, expires_at=700,
    )
    return key, directory, reviewer, plan, grant


def test_signed_live_grant_is_consumed_once_without_emitting_capability(live):
    key, directory, reviewer, plan, grant = live
    signature = key.sign(grant.signing_bytes())
    assert reviewer.consume_for_review(grant, signature, plan) is None
    database, = directory.iterdir()
    with closing(sqlite3.connect(database)) as db:
        grant_id, digest, reviewed = db.execute("SELECT * FROM offline_live_grant_reviews").fetchone()
        assert (grant_id, reviewed) == (grant.grant_id, 100)
        assert len(digest) == 64
    assert signature not in database.read_bytes()
    reopened = LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 110)
    with pytest.raises(ValueError, match="already been consumed"):
        reopened.consume_for_review(grant, signature, plan)


def test_dry_grant_and_dry_signature_cannot_upgrade(live):
    key, directory, reviewer, plan, grant = live
    dry = DryRunApproval(
        approval_id=grant.grant_id, mode="dry_run", source_sha256=plan.source_sha256,
        protocol_sha256=plan.protocol_sha256, runtime_sha256=plan.native_sha256,
        workspace_sha256=plan.workspace_binding, model=plan.model, phase_schema_sha256=plan.phase_schema_sha256,
        expires_at=grant.expires_at, cases=plan.cases,
    )
    signature = key.sign(dry.model_dump_json().encode())
    with pytest.raises(ValueError):
        reviewer.consume_for_review(dry, signature, plan)
    with pytest.raises(ValueError, match="operator signature"):
        reviewer.consume_for_review(grant, signature, plan)
    signed_live = key.sign(grant.signing_bytes())
    with pytest.raises(ValueError):
        reviewer.consume_for_review(grant.model_copy(update={"mode": "dry_run"}), signed_live, plan)
    assert review_count(directory) == 0


@pytest.mark.parametrize("field", [
    "source_sha256", "protocol_sha256", "account_binding", "workspace_binding", "phase_schema_sha256", "cases",
])
def test_signed_grant_binds_exact_independently_supplied_plan(live, field):
    key, directory, reviewer, plan, grant = live
    replacement = {
        "phase_schema_sha256": ("c" * 64, "b" * 64),
        "cases": tuple(reversed(plan.cases)),
    }.get(field, "c" * 64)
    altered = plan.model_copy(update={field: replacement})
    signature = key.sign(grant.signing_bytes())
    with pytest.raises(ValueError, match="trusted ledger or calibration plan"):
        reviewer.consume_for_review(grant, signature, altered)
    with pytest.raises(ValueError, match="operator signature"):
        reviewer.consume_for_review(grant.model_copy(update={"plan": altered}), signature, altered)
    assert review_count(directory) == 0


@pytest.mark.parametrize(("field", "wrong"), [
    ("runtime_version", "0.168.0"), ("native_sha256", DIGEST),
    ("model", "other-model"), ("effort", "high"),
])
def test_policy_rejects_runtime_model_and_effort_drift(live, field, wrong):
    _, _, _, plan, _ = live
    with pytest.raises(ValueError):
        LiveCalibrationPlan.model_validate(plan.model_copy(update={field: wrong}))


def test_cannot_replay_in_a_different_ledger_or_with_another_operator(live, tmp_path):
    key, directory, reviewer, plan, grant = live
    another = tmp_path / "second-ledger"
    another.mkdir(mode=0o700)
    provision(another)
    outside = LiveGrantReview(another, trusted_operator_key=key.public_key(), clock=lambda: 100)
    with pytest.raises(ValueError, match="trusted ledger"):
        outside.consume_for_review(grant, key.sign(grant.signing_bytes()), plan)
    rogue = Ed25519PrivateKey.from_private_bytes(b"X" * 32)
    with pytest.raises(ValueError, match="operator signature"):
        reviewer.consume_for_review(grant, rogue.sign(grant.signing_bytes()), plan)
    assert review_count(directory) == review_count(another) == 0


@pytest.mark.parametrize("now", [89.0, 700.0, float("nan")])
def test_rejects_grant_outside_validity_window(live, now):
    key, directory, _, plan, grant = live
    reviewer = LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: now)
    with pytest.raises(ValueError, match="expired, not yet valid, or clock unavailable"):
        reviewer.consume_for_review(grant, key.sign(grant.signing_bytes()), plan)


def test_concurrent_consumers_have_one_winner(live):
    key, directory, _, plan, grant = live
    signature = key.sign(grant.signing_bytes())
    barrier = Barrier(2)

    def attempt():
        reviewer = LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 100)
        barrier.wait(timeout=5)
        try:
            reviewer.consume_for_review(grant, signature, plan)
        except ValueError as exc:
            assert "already been consumed" in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=5) for future in futures) == [False, True]


def test_signed_payload_includes_fixed_limits(live):
    _, _, _, _, grant = live
    document = json.loads(grant.signing_bytes().split(b"\x00", 1)[1])
    assert document["limits"] == {
        "cases": 36, "max_calls": 72, "phase_seconds": 60, "cohort_seconds": 72 * 60,
        "max_grant_seconds": 77 * 60,
    }


def test_rejects_ledger_symlink(live, tmp_path):
    key, directory, reviewer, plan, grant = live
    outside = tmp_path / "outside"
    outside.touch(mode=0o600)
    database = directory / "issue6-live-reviews.sqlite"
    database.unlink()
    database.symlink_to(outside)
    with pytest.raises(ValueError, match="regular file"):
        reviewer.consume_for_review(grant, key.sign(grant.signing_bytes()), plan)
    assert outside.stat().st_size == 0


def test_consumed_grant_cannot_recreate_deleted_ledger_at_same_path(live):
    key, directory, reviewer, plan, grant = live
    signature = key.sign(grant.signing_bytes())
    reviewer.consume_for_review(grant, signature, plan)
    database = directory / "issue6-live-reviews.sqlite"
    database.unlink()
    with pytest.raises(ValueError, match="must be provisioned"):
        reviewer.consume_for_review(grant, signature, plan)
    with pytest.raises(ValueError, match="must be provisioned"):
        LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 100)
    assert not database.exists()
    database.touch(mode=0o600)
    with pytest.raises(ValueError, match="must be provisioned"):
        LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 100)
    assert database.stat().st_size == 0


def test_replacement_generation_rejects_previously_signed_grant(live):
    key, directory, reviewer, plan, grant = live
    signature = key.sign(grant.signing_bytes())
    reviewer.consume_for_review(grant, signature, plan)
    (directory / "issue6-live-reviews.sqlite").unlink()
    provision(directory, generation="1" * 64)
    with pytest.raises(ValueError, match="generation does not match"):
        reviewer.consume_for_review(grant, signature, plan)
    recreated = LiveGrantReview(directory, trusted_operator_key=key.public_key(), clock=lambda: 100)
    with pytest.raises(ValueError, match="trusted ledger"):
        recreated.consume_for_review(grant, signature, plan)
    assert review_count(directory) == 0


def test_canonical_state_alias_cannot_redirect_an_existing_reviewer(live, tmp_path):
    key, directory, _, plan, grant = live
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    reviewer = LiveGrantReview(alias, trusted_operator_key=key.public_key(), clock=lambda: 100)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    provision(elsewhere)
    alias.unlink()
    alias.symlink_to(elsewhere, target_is_directory=True)
    reviewer.consume_for_review(grant, key.sign(grant.signing_bytes()), plan)
    assert review_count(directory) == 1
    assert review_count(elsewhere) == 0


def test_rejects_state_with_group_writable_ancestor(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o700)
    state = parent / "state"
    state.mkdir(mode=0o700)
    provision(state)
    parent.chmod(0o770)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    with pytest.raises(ValueError, match="untrusted path ancestor"):
        LiveGrantReview(state, trusted_operator_key=key.public_key())


def test_canonical_schema_rejects_trigger_that_would_remove_spent_grant(live):
    key, directory, reviewer, plan, grant = live
    signature = key.sign(grant.signing_bytes())
    with closing(sqlite3.connect(directory / "issue6-live-reviews.sqlite")) as db, db:
        db.execute("""
            CREATE TRIGGER erase_spent AFTER INSERT ON offline_live_grant_reviews
            BEGIN DELETE FROM offline_live_grant_reviews WHERE grant_id=NEW.grant_id; END
        """)
    # The schema was valid when reviewer was constructed. It must be checked again in the write.
    for _ in range(3):
        with pytest.raises(ValueError, match="canonical schema"):
            reviewer.consume_for_review(grant, signature, plan)
    with pytest.raises(ValueError, match="canonical schema"):
        LiveGrantReview(directory, trusted_operator_key=key.public_key())
    assert review_count(directory) == 0


@pytest.mark.parametrize("ddl", [
    "CREATE VIEW copied_identity AS SELECT * FROM offline_live_ledger_identity",
    "ALTER TABLE offline_live_grant_reviews ADD COLUMN unrelated TEXT",
])
def test_canonical_schema_rejects_other_sql_objects_or_table_drift(live, ddl):
    key, directory, reviewer, plan, grant = live
    with closing(sqlite3.connect(directory / "issue6-live-reviews.sqlite")) as db, db:
        db.execute(ddl)
    with pytest.raises(ValueError, match="canonical schema"):
        reviewer.consume_for_review(grant, key.sign(grant.signing_bytes()), plan)


def test_grant_lifetime_bounded_by_cohort_plus_five_minutes(live):
    _, _, _, _, grant = live
    for seconds in (0, -1, 77 * 60 + 1):
        invalid = grant.model_copy(update={"expires_at": grant.issued_at + seconds})
        with pytest.raises(ValueError, match="grant lifetime"):
            LiveCalibrationGrant.model_validate(invalid)
    maximum = grant.model_copy(update={"expires_at": grant.issued_at + 77 * 60})
    assert LiveCalibrationGrant.model_validate(maximum) == maximum


def test_independent_openssl_signing_vector(live):
    _, _, _, _, grant = live
    vector = grant.model_copy(update={"ledger_binding": "0" * 64})
    payload = vector.signing_bytes()
    # Independently encoded expected JSON and OpenSSL pkeyutl with seed bytes 00..1f.
    assert hashlib.sha256(payload).hexdigest() == "c1829d161f52767addfc205fd666082770d7da98d89eb53e221115fca4e86040"
    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(
        "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
    ))
    key.verify(bytes.fromhex(
        "168182b88c925ff5bfe3b471d8a26b78bcd902cf858a02ee47a6ac0616e72c4df"
        "12827c3a3b34bce44539510700e3662ede74e5ee10cb42b2201892be62cdb0a"
    ), payload)
