import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.evaluation.issue6_build_pilot import _one_assignment
from metis.evaluation.issue6_pilot_admission import (
    COHORT_SECONDS,
    PHASE_SECONDS,
    DryRunAdmission,
    DryRunApproval,
    DryRunPhase,
    FrozenCase,
    workspace_binding,
)

DIGEST = "a" * 64


@pytest.fixture
def dry_run(tmp_path):
    scheduler = AgentScheduler(tmp_path / "ledger.sqlite", BridgeHost())
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=2,
                        catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted")
    workspace = tmp_path / "claimed-workspace"
    approval = DryRunApproval(
        approval_id="operator-approval-1", mode="dry_run",
        source_sha256=DIGEST, protocol_sha256=DIGEST, runtime_sha256=DIGEST,
        workspace_sha256=workspace_binding(workspace), model="scripted", expires_at=10_000,
        phase_schema_sha256=(DIGEST, DIGEST),
        cases=tuple(FrozenCase(case_id=f"case-{i}", artifact_hmac=f"{i:064x}") for i in range(36)),
    )
    clock = [100.0]
    admission = DryRunAdmission(scheduler, clock=lambda: clock[0], wall_clock=lambda: 1_000)
    admission.register(approval)
    return scheduler, workspace, approval, clock, admission


def start(scheduler, run_id=None):
    first = run_id is None
    if first:
        artifact = scheduler.database.parent / "test-public.json"
        artifact.write_text("{}")
        run_id = scheduler.session.intake(
            title="Benign build log", description="Offline dry run", paths=[artifact],
            categories=["misc"], max_actions=2, wall_seconds=120,
        )["run_id"]
    wave = scheduler.ledger.create_wave(
        run_id, mode="delegated", plan_policy=_one_assignment,
        reason=None if first else "Review the provisional option against the same input",
    )
    scheduler.enqueue(run_id, wave["wave_id"])
    job, = scheduler.dispatch(run_id)["started"]
    return run_id, job["assignment_id"], job["attempt_id"]


def phase(number=1, case=0):
    return DryRunPhase(case_id=f"case-{case}", phase=number, artifact_hmac=f"{case:064x}",
                       prompt_hmac=DIGEST, schema_sha256=DIGEST)


def test_restart_and_different_workspace_cannot_redeem_same_approval(dry_run, tmp_path):
    scheduler, workspace, approval, _, admission = dry_run
    with pytest.raises(ValueError, match="workspace"):
        admission.claim(approval, tmp_path / "other")
    different_root = approval.model_copy(update={"workspace_sha256": workspace_binding(tmp_path / "other")})
    with pytest.raises(ValueError, match="mismatches"):
        admission.claim(different_root, tmp_path / "other")
    admission.claim(approval, workspace)
    recovered = DryRunAdmission(scheduler, wall_clock=lambda: 1_000)
    with pytest.raises(ValueError, match="consumed"):
        recovered.claim(approval, workspace)
    with pytest.raises(ValueError, match="claimed cohort"):
        recovered.open_phase("case-0", 1)


def test_only_one_concurrent_controller_consumes_approval(dry_run):
    scheduler, workspace, approval, _, _ = dry_run
    barrier = Barrier(2)

    def attempt():
        admission = DryRunAdmission(scheduler, wall_clock=lambda: 1_000)
        barrier.wait(timeout=5)
        try:
            admission.claim(approval, workspace)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=5) for future in futures) == [False, True]


def test_mismatched_contract_and_expired_approval_refused(dry_run):
    scheduler, workspace, approval, _, admission = dry_run
    with pytest.raises(ValueError, match="mismatches"):
        admission.claim(approval.model_copy(update={"model": "different"}), workspace)
    with pytest.raises(ValueError, match="expired"):
        DryRunAdmission(scheduler, wall_clock=lambda: 10_000).claim(approval, workspace)
    with pytest.raises(ValueError):
        admission.claim(approval.model_copy(update={"mode": "real_model"}), workspace)
    admission.claim(approval, workspace)


def test_failed_receipt_insert_rolls_back_turn_charge_and_receipt(dry_run):
    scheduler, workspace, approval, _, admission = dry_run
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    job = start(scheduler)
    with closing(sqlite3.connect(scheduler.database)) as db, db:
        db.execute("""
            CREATE TRIGGER reject_dry_receipt BEFORE INSERT ON issue6_dry_reservations
            BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected receipt failure"):
        admission.reserve_phase(*job, phase())
    assert scheduler.model_turn_budget(job[0])["reserved"] == 0
    with closing(sqlite3.connect(scheduler.database)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM issue6_dry_reservations").fetchone() == (0,)
        db.execute("DROP TRIGGER reject_dry_receipt")
    reservation = admission.reserve_phase(*job, phase())
    assert scheduler.model_turn_budget(job[0])["reserved"] == 1
    with closing(sqlite3.connect(scheduler.database)) as db:
        assert db.execute("""
            SELECT t.run_id, t.assignment_id, t.attempt_id, r.commitment
            FROM issue6_dry_reservations r JOIN agent_turn_reservations t ON t.id = r.reservation_id
            WHERE r.reservation_id = ?
        """, (reservation,)).fetchone() == (*job, phase().model_dump_json())
    with pytest.raises(ValueError, match="phase budget"):
        admission.reserve_phase(*job, phase())
    assert scheduler.model_turn_budget(job[0])["reserved"] == 1


def test_phase_and_cohort_cutoffs_are_monotonic_and_cannot_be_extended(dry_run):
    scheduler, workspace, approval, clock, admission = dry_run
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    job = start(scheduler)
    clock[0] += PHASE_SECONDS - 1
    admission.open_phase("case-0", 1)
    clock[0] += 1
    with pytest.raises(ValueError, match="phase deadline"):
        admission.reserve_phase(*job, phase())
    assert scheduler.model_turn_budget(job[0])["reserved"] == 0
    clock[0] = 100 + COHORT_SECONDS
    with pytest.raises(ValueError, match="cohort deadline"):
        admission.open_phase("case-1", 1)


def test_review_requires_completed_prior_handoff_and_order(dry_run):
    scheduler, workspace, approval, _, admission = dry_run
    admission.claim(approval, workspace)
    job = start(scheduler)
    for number, case in [(1, 1), (2, 0), (1, 0)]:
        admission.open_phase(f"case-{case}", number)
    with pytest.raises(ValueError, match="out of order"):
        admission.reserve_phase(*job, phase(case=1))
    with pytest.raises(ValueError, match="phase budget"):
        admission.reserve_phase(*job, phase(number=2))
    admission.reserve_phase(*job, phase())
    with pytest.raises(ValueError, match="unresolved"):
        admission.reserve_phase(*job, phase(number=2))
    scheduler.complete(*job, {
        "hypothesis": "A synthetic diagnosis was chosen.",
        "evidence": "Only the opaque format was checked.",
        "falsifier": "The oracle may reject the diagnosis.",
        "next_action": "Review the provisional diagnosis.",
        "event_sequences": [0],
    })
    reviewer = start(scheduler, job[0])
    admission.reserve_phase(*reviewer, phase(number=2))
    assert scheduler.model_turn_budget(job[0])["reserved"] == 2


def test_receipt_rejects_artifact_or_schema_drift_before_charging(dry_run):
    scheduler, workspace, approval, _, admission = dry_run
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    job = start(scheduler)
    with pytest.raises(ValueError, match="artifact receipt"):
        admission.reserve_phase(*job, phase().model_copy(update={"artifact_hmac": DIGEST}))
    with pytest.raises(ValueError, match="schema receipt"):
        admission.reserve_phase(*job, phase().model_copy(update={"schema_sha256": "b" * 64}))
    assert scheduler.model_turn_budget(job[0])["reserved"] == 0


@pytest.mark.parametrize("invalid", [True, False, 1.0, 2.0, "1", "2"])
def test_receipt_phase_requires_an_exact_integer(invalid):
    with pytest.raises(ValueError, match="phase must be an integer"):
        phase(number=invalid)
    with pytest.raises(ValueError, match="phase must be an integer"):
        DryRunPhase.model_validate(phase().model_copy(update={"phase": invalid}))


def test_symlink_redirect_is_rejected_before_reservation(dry_run, tmp_path):
    scheduler, workspace, approval, clock, _ = dry_run
    original = scheduler.database
    alias = tmp_path / "db-link"
    alias.symlink_to(original)
    scheduler.database = alias
    admission = DryRunAdmission(scheduler, clock=lambda: clock[0], wall_clock=lambda: 1_000)
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    alternate = tmp_path / "alternate.sqlite"
    other = AgentScheduler(alternate, BridgeHost())
    other.configure(global_slots=1, specialist_turn_budget=2,
                    catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted")
    job = start(other)
    DryRunAdmission(other)
    alias.unlink()
    alias.symlink_to(alternate)
    with pytest.raises(ValueError, match="scheduler database differs"):
        admission.reserve_phase(*job, phase())
    assert other.model_turn_budget(job[0])["reserved"] == 0


@pytest.mark.parametrize("other_state", ["ready", "exhausted", "expired", "cancelled"])
def test_redirect_after_path_check_does_not_mutate_other_database(
    dry_run, tmp_path, monkeypatch, other_state,
):
    scheduler, workspace, approval, _, admission = dry_run
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    other = AgentScheduler(tmp_path / "alternate.sqlite", BridgeHost())
    other.configure(global_slots=1, specialist_turn_budget=2,
                    catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted")
    job = start(other)
    alternate_admission = DryRunAdmission(other, wall_clock=lambda: 1_000)
    alternate_admission.register(approval)
    alternate_admission.claim(approval, workspace)
    with closing(sqlite3.connect(other.database)) as db, db:
        if other_state == "exhausted":
            db.execute("UPDATE agent_run_turn_budgets SET turns_reserved=turn_limit")
        if other_state == "expired":
            db.execute("UPDATE agent_jobs SET deadline=1")
    if other_state == "cancelled":
        other.session.cancel(job[0])
    with closing(sqlite3.connect(other.database)) as db:
        before = {
            table: db.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("agent_jobs", "agent_job_log", "agent_run_turn_budgets",
                          "agent_turn_reservations", "issue6_dry_reservations")
        }
    monkeypatch.setattr(scheduler, "reserve_model_turn", other.reserve_model_turn)
    with pytest.raises(ValueError, match="reservation database differs"):
        admission.reserve_phase(*job, phase())
    with closing(sqlite3.connect(other.database)) as db:
        for table, rows in before.items():
            assert db.execute(f"SELECT * FROM {table}").fetchall() == rows


@pytest.mark.parametrize("edit", ["claimed = 0", "binding = '{}'"])
def test_reservation_rechecks_claim_and_binding_in_transaction(dry_run, edit):
    scheduler, workspace, approval, _, admission = dry_run
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    job = start(scheduler)
    with closing(sqlite3.connect(scheduler.database)) as db, db:
        db.execute(f"UPDATE issue6_dry_approvals SET {edit}")
    with pytest.raises(ValueError, match="claimed approval does not match"):
        admission.reserve_phase(*job, phase())
    assert scheduler.model_turn_budget(job[0])["reserved"] == 0
