import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from multiprocessing import get_context
from pathlib import Path

import pytest
from pydantic import ValidationError

from metis.core.study_token_admission import (
    SlotTokenPin,
    StudyTokenAdmission,
    StudyTokenPin,
    TokenAdmissionReceipt,
    TokenAttempt,
    TokenLaunchClaim,
    TokenLaunchOutcome,
)

STUDY = StudyTokenPin(study_id="issue8", protocol_sha256="a" * 64, runtime_sha256="b" * 64,
                      model_sha256="c" * 64, token_limit=100)
SLOT = SlotTokenPin(run_id="run1", task_id="task", repetition=0, arm="full", token_limit=70)
ATTEMPT = TokenAttempt(assignment_id="assignment", attempt_id="attempt1", turn_reservation_id=1,
                       prompt_sha256="d" * 64, tokens=60)


def _concurrent_reservation(database: Path, distinct_slots: bool, index: int, barrier) -> str:
    slot = (
        SLOT.model_copy(update={"run_id": f"run{index}", "repetition": index})
        if distinct_slots else SLOT
    )
    attempt = ATTEMPT.model_copy(update={
        "turn_reservation_id": index + 1, "tokens": 60 if distinct_slots else 40,
    })
    barrier.wait(timeout=10)
    try:
        StudyTokenAdmission(database).reserve(STUDY, slot, attempt)
    except ValueError as exc:
        return str(exc)
    return "admitted"


@pytest.mark.parametrize(("distinct_slots", "exhausted"), [
    (False, "run token budget exhausted"),
    (True, "study token budget exhausted"),
])
def test_parallel_controllers_share_study_and_run_caps(tmp_path, distinct_slots, exhausted):
    database = tmp_path / "state.sqlite"
    context = get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        requests = [pool.submit(_concurrent_reservation, database, distinct_slots, index, barrier)
                    for index in range(2)]
        assert sorted(request.result(timeout=15) for request in requests) == [
            "admitted", exhausted,
        ]


@pytest.mark.parametrize("failure", [TimeoutError, OSError])
def test_timeout_or_failure_retains_entire_allowance(tmp_path, failure):
    database = tmp_path / "state.sqlite"
    with pytest.raises(failure):
        StudyTokenAdmission(database).reserve(STUDY, SLOT, ATTEMPT)
        raise failure("runtime did not return a receipt")
    restarted = StudyTokenAdmission(database)
    with pytest.raises(ValueError, match="already has a token receipt"):
        restarted.reserve(STUDY, SLOT, ATTEMPT.model_copy(update={"attempt_id": "retry"}))
    next_attempt = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 11})
    with pytest.raises(ValueError, match="run token budget exhausted"):
        restarted.reserve(STUDY, SLOT, next_attempt)


@pytest.mark.parametrize(("field", "value"), [
    ("study_id", "alternate"), ("protocol_sha256", "e" * 64),
    ("runtime_sha256", "e" * 64), ("model_sha256", "e" * 64), ("token_limit", 101),
])
def test_study_pin_cannot_change(tmp_path, field, value):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    admission.reserve(STUDY, SLOT, ATTEMPT)
    changed = STUDY.model_copy(update={field: value})
    with pytest.raises(ValueError, match="study token pin mismatch"):
        admission.reserve(changed, SLOT, ATTEMPT)


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", "replacement-run"), ("task_id", "replacement-task"),
    ("repetition", 1), ("arm", "other"), ("token_limit", 71),
])
def test_run_and_slot_pin_cannot_change(tmp_path, field, value):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    admission.reserve(STUDY, SLOT, ATTEMPT)
    changed = SLOT.model_copy(update={field: value})
    with pytest.raises(ValueError, match="run or study slot token pin mismatch"):
        admission.reserve(STUDY, changed, ATTEMPT)


def test_denied_reservations_roll_back_and_success_is_frozen(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    with pytest.raises(ValueError, match="run token budget exhausted"):
        admission.reserve(STUDY, SLOT.model_copy(update={"token_limit": 50}), ATTEMPT)
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    assert (receipt.study, receipt.slot, receipt.attempt) == (STUDY, SLOT, ATTEMPT)
    with pytest.raises(ValidationError):
        receipt.attempt.tokens = 1
    remaining = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 10})
    assert admission.reserve(STUDY, SLOT, remaining).attempt.tokens == 10


@pytest.mark.parametrize("tokens", [True, "1", 0, -1])
def test_invalid_amount_cannot_bypass_validation(tmp_path, tokens):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    with pytest.raises(ValidationError):
        admission.reserve(STUDY, SLOT, ATTEMPT.model_copy(update={"tokens": tokens}))

def _concurrent_claim(database: Path, receipt: TokenAdmissionReceipt, barrier) -> str:
    barrier.wait(timeout=10)
    try:
        StudyTokenAdmission(database).claim_for_launch(receipt)
    except ValueError as exc:
        return str(exc)
    return "claimed"


def _claim_then_crash(database: Path, receipt: TokenAdmissionReceipt) -> None:
    StudyTokenAdmission(database).claim_for_launch(receipt)
    os._exit(91)


def test_only_one_parallel_controller_claims_an_admission(tmp_path):
    database = tmp_path / "state.sqlite"
    receipt = StudyTokenAdmission(database).reserve(STUDY, SLOT, ATTEMPT)
    context = get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        requests = [pool.submit(_concurrent_claim, database, receipt, barrier) for _ in range(2)]
        assert sorted(request.result(timeout=15) for request in requests) == [
            "claimed", "token launch already claimed or nonce unavailable",
        ]


def test_controller_crash_after_claim_rejects_relaunch_and_retains_charge(tmp_path):
    database = tmp_path / "state.sqlite"
    receipt = StudyTokenAdmission(database).reserve(STUDY, SLOT, ATTEMPT)
    process = get_context("spawn").Process(target=_claim_then_crash, args=(database, receipt))
    process.start()
    try:
        process.join(timeout=15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()

    restarted = StudyTokenAdmission(database)
    with pytest.raises(ValueError, match="already claimed"):
        restarted.claim_for_launch(receipt)
    next_attempt = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 11})
    with pytest.raises(ValueError, match="run token budget exhausted"):
        restarted.reserve(STUDY, SLOT, next_attempt)


@pytest.mark.parametrize(("record", "field", "value"), [
    ("study", "protocol_sha256", "e" * 64),
    ("study", "runtime_sha256", "e" * 64),
    ("study", "model_sha256", "e" * 64),
    ("slot", "run_id", "different-run"),
    ("slot", "task_id", "different-task"),
    ("slot", "repetition", 1),
    ("slot", "arm", "other"),
    ("attempt", "assignment_id", "different-assignment"),
    ("attempt", "attempt_id", "different-attempt"),
    ("attempt", "turn_reservation_id", 2),
    ("attempt", "prompt_sha256", "e" * 64),
    ("attempt", "tokens", 1),
])
def test_claim_requires_exact_committed_receipt(tmp_path, record, field, value):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    changed = getattr(receipt, record).model_copy(update={field: value})
    with pytest.raises(ValueError, match="match committed reservation"):
        admission.claim_for_launch(receipt.model_copy(update={record: changed}))
    assert admission.claim_for_launch(receipt).receipt == receipt


def test_no_claim_for_uncommitted_admission(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    invented = TokenAdmissionReceipt(study=STUDY, slot=SLOT, attempt=ATTEMPT)
    with pytest.raises(ValueError, match="match committed reservation"):
        admission.claim_for_launch(invented)


def test_nonce_cannot_bind_multiple_launches(tmp_path, monkeypatch):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    monkeypatch.setattr("metis.core.study_token_admission.secrets.token_hex", lambda _: "2" * 32)
    first = admission.reserve(STUDY, SLOT, ATTEMPT)
    second = admission.reserve(STUDY, SLOT, ATTEMPT.model_copy(
        update={"turn_reservation_id": 2, "tokens": 10},
    ))
    assert admission.claim_for_launch(first).nonce == "2" * 32
    with pytest.raises(ValueError, match="nonce unavailable"):
        admission.claim_for_launch(second)


def test_outcome_requires_exact_nonce_and_receipt_and_can_only_be_written_once(tmp_path):
    database = tmp_path / "state.sqlite"
    admission = StudyTokenAdmission(database)
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    outcome = TokenLaunchOutcome(status="completed", exit_status=0, observed_work=2)
    invented = TokenLaunchClaim(receipt=receipt, nonce="0" * 32)
    with pytest.raises(ValueError, match="match committed nonce"):
        admission.record_outcome(invented, outcome)

    claim = admission.claim_for_launch(receipt)
    with pytest.raises(ValueError, match="has not been consumed"):
        admission.record_outcome(claim, outcome)
    admission.consume_launch_claim(claim)
    with pytest.raises(ValueError, match="already consumed"):
        admission.consume_launch_claim(claim)
    wrong_nonce = "1" * 32 if claim.nonce == "0" * 32 else "0" * 32
    with pytest.raises(ValueError, match="match committed nonce"):
        admission.record_outcome(claim.model_copy(update={"nonce": wrong_nonce}), outcome)
    other_attempt = ATTEMPT.model_copy(update={"attempt_id": "other"})
    other_receipt = receipt.model_copy(update={"attempt": other_attempt})
    with pytest.raises(ValueError, match="match committed reservation"):
        admission.record_outcome(claim.model_copy(update={"receipt": other_receipt}), outcome)

    with pytest.raises(ValueError, match="exceeds admitted token"):
        admission.record_outcome(claim, outcome.model_copy(update={"observed_work": ATTEMPT.tokens + 1}))
    admission.record_outcome(claim, outcome)
    with pytest.raises(ValueError, match="already recorded"):
        StudyTokenAdmission(database).record_outcome(claim, outcome)
    with pytest.raises(ValueError, match="already claimed"):
        admission.claim_for_launch(receipt)
    with pytest.raises(ValueError, match="run token budget exhausted"):
        admission.reserve(STUDY, SLOT, ATTEMPT.model_copy(
            update={"turn_reservation_id": 2, "tokens": 11},
        ))
    with closing(sqlite3.connect(database)) as db:
        assert db.execute(
            "SELECT nonce, status, exit_status, observed_work FROM study_token_outcomes"
        ).fetchall() == [(claim.nonce, "completed", 0, 2)]


@pytest.mark.parametrize(("status", "exit_status", "work"), [
    ("unknown", 0, 0), ("completed", 1, 0), ("completed", 0, None),
    ("cap_denied", 0, 0), ("unsupported_graph", 75, None),
    ("server_error", 74, 0), ("timeout", -9, 1), ("cancelled", -9, 1),
    ("launch_failed", -9, None), ("lost", -9, None), ("completed", False, 0),
])
def test_invalid_terminal_observations_are_rejected(status, exit_status, work):
    with pytest.raises(ValidationError):
        TokenLaunchOutcome(status=status, exit_status=exit_status, observed_work=work)


def _concurrent_outcome(database: Path, claim: TokenLaunchClaim, outcome: TokenLaunchOutcome, barrier) -> str:
    barrier.wait(timeout=10)
    try:
        StudyTokenAdmission(database).record_outcome(claim, outcome)
    except ValueError as exc:
        return str(exc)
    return "recorded"


def test_only_one_parallel_controller_records_an_outcome(tmp_path):
    database = tmp_path / "state.sqlite"
    admission = StudyTokenAdmission(database)
    claim = admission.claim_for_launch(admission.reserve(STUDY, SLOT, ATTEMPT))
    admission.consume_launch_claim(claim)
    outcome = TokenLaunchOutcome(status="timeout", exit_status=-9)

    context = get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        requests = [pool.submit(_concurrent_outcome, database, claim, outcome, barrier) for _ in range(2)]
        assert sorted(request.result(timeout=15) for request in requests) == [
            "recorded", "token launch outcome already recorded",
        ]

    with closing(sqlite3.connect(database)) as db:
        assert db.execute(
            "SELECT nonce, status, exit_status, observed_work FROM study_token_outcomes"
        ).fetchall() == [(claim.nonce, "timeout", -9, None)]
    with pytest.raises(ValueError, match="already claimed"):
        admission.claim_for_launch(claim.receipt)
    with pytest.raises(ValueError, match="run token budget exhausted"):
        admission.reserve(STUDY, SLOT, ATTEMPT.model_copy(
            update={"turn_reservation_id": 2, "tokens": 11},
        ))


def test_admission_from_prior_schema_can_be_claimed(tmp_path):
    database = tmp_path / "state.sqlite"
    admission = StudyTokenAdmission(database)
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    # Model a persisted #86 database without the two new tables.
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("DROP TABLE study_token_outcomes")
        db.execute("DROP TABLE study_token_launches")
    assert admission.claim_for_launch(receipt).receipt == receipt


def test_legacy_launch_claims_are_consumed_during_schema_migration(tmp_path):
    database = tmp_path / "state.sqlite"
    admission = StudyTokenAdmission(database)
    claim = admission.claim_for_launch(admission.reserve(STUDY, SLOT, ATTEMPT))
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("ALTER TABLE study_token_launches DROP COLUMN consumed")
    with admission._transaction() as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (1,)
    with pytest.raises(ValueError, match="already consumed"):
        admission.consume_launch_claim(claim)


def test_committed_manifest_pin_binds_reservation_claim_and_outcome(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    pinned = STUDY.model_copy(update={"native_manifest_sha256": "1" * 64})
    receipt = admission.reserve(pinned, SLOT, ATTEMPT)
    alternate = pinned.model_copy(update={"native_manifest_sha256": "2" * 64})
    with pytest.raises(ValueError, match="study token pin mismatch"):
        admission.reserve(alternate, SLOT, ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 1}))
    with pytest.raises(ValueError, match="committed reservation"):
        admission.claim_for_launch(receipt.model_copy(update={"study": alternate}))

    claim = admission.claim_for_launch(receipt)
    admission.consume_launch_claim(claim)
    with pytest.raises(ValueError, match="committed native manifest"):
        admission.record_outcome(claim, TokenLaunchOutcome(status="launch_failed"))
    admission.record_outcome(claim, TokenLaunchOutcome(status="launch_failed", native_manifest_sha256="1" * 64))
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT native_manifest_sha256 FROM study_token_outcomes").fetchall() == [("1" * 64,)]


def test_legacy_manifest_migration_preserves_charges_and_refuses_repinning(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    with closing(sqlite3.connect(admission.database)) as db, db:
        db.execute("ALTER TABLE study_token_pins DROP COLUMN native_manifest_sha256")
        db.execute("ALTER TABLE study_token_outcomes DROP COLUMN native_manifest_sha256")
    assert admission.claim_for_launch(receipt).receipt == receipt
    subsequent = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 11})
    pinned = STUDY.model_copy(update={"native_manifest_sha256": "1" * 64})
    with pytest.raises(ValueError, match="study token pin mismatch"):
        admission.reserve(pinned, SLOT, subsequent)
    with pytest.raises(ValueError, match="run token budget exhausted"):
        admission.reserve(STUDY, SLOT, subsequent)
