from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from metis.evaluation.reboot_evidence import (
    ArmedObservation,
    BootObservation,
    PostBootObservation,
    RebootEvidence,
    RecoveryObservation,
    WorkerIdentity,
    classify_reboot_evidence,
)


def _time(seconds: int) -> datetime:
    return datetime(2026, 11, 19, tzinfo=UTC) + timedelta(seconds=seconds)


@pytest.fixture
def complete() -> RebootEvidence:
    worker = WorkerIdentity(run_id="fixture-run", worker_id="armed-worker", operation_id="operation-one")
    return RebootEvidence(
        previous_boot=BootObservation(host_id="fixture-host", boot_id=UUID(int=1), started_at=_time(0)),
        armed=ArmedObservation(captured_at=_time(20), worker=worker, execution_started_at=_time(10),
                               deadline=_time(300), remaining_actions=28),
        next_boot=BootObservation(host_id="fixture-host", boot_id=UUID(int=2), started_at=_time(30)),
        post_boot=PostBootObservation(
            captured_at=_time(40), run_id=worker.run_id, run_state="executing", active_worker=worker,
            remaining_actions=28, surviving_worker=False, audit_chain_verified=True,
            armed_execution_recorded=True, armed_operation_terminal=False,
        ),
        recovery=RecoveryObservation(captured_at=_time(50), boot_id=UUID(int=2), worker=worker,
                                     audit_continuity_verified=True, run_state="planning",
                                     worker_teardown="confirmed", remaining_actions=28),
        repeated_recovery=RecoveryObservation(captured_at=_time(60), boot_id=UUID(int=2), worker=worker,
                                              audit_continuity_verified=True, run_state="planning",
                                              worker_teardown="not_running", remaining_actions=28),
    )


def test_verified_same_identity_recovery_preserves_budget_and_repeats_idempotently(complete):
    preserved = RebootEvidence.model_validate_json(complete.model_dump_json())
    verdict = classify_reboot_evidence(preserved)
    assert (verdict.status, verdict.reason) == ("passed", "same_worker_recovered")


def test_differently_armed_identity_is_inconclusive_even_if_successor_can_recover(complete):
    successor = complete.armed.worker.model_copy(update={"worker_id": "successor", "operation_id": "operation-two"})
    post_boot = complete.post_boot.model_copy(update={"active_worker": successor, "remaining_actions": 27})
    verdict = classify_reboot_evidence(complete.model_copy(update={"post_boot": post_boot}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "worker_changed")


def test_reused_worker_with_different_operation_is_inconclusive(complete):
    successor = complete.armed.worker.model_copy(update={"operation_id": "operation-two"})
    post_boot = complete.post_boot.model_copy(update={"active_worker": successor})
    verdict = classify_reboot_evidence(complete.model_copy(update={"post_boot": post_boot}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "worker_changed")


def test_preboot_expiration_does_not_pass_after_worker_has_gone(complete):
    armed = complete.armed.model_copy(update={"deadline": _time(24)})
    post_boot = complete.post_boot.model_copy(update={"active_worker": None, "run_state": "planning"})
    verdict = classify_reboot_evidence(complete.model_copy(update={"armed": armed, "post_boot": post_boot}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "arm_expired")


def test_changed_boot_id_without_a_live_worker_is_inconclusive(complete):
    post_boot = complete.post_boot.model_copy(update={"active_worker": None, "run_state": "planning"})
    verdict = classify_reboot_evidence(complete.model_copy(update={"post_boot": post_boot}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "worker_missing")


def test_unchanged_boot_does_not_pass(complete):
    verdict = classify_reboot_evidence(complete.model_copy(update={"next_boot": complete.previous_boot}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "boot_unchanged")


@pytest.mark.parametrize(("section", "changed", "status", "reason"), [
    ("next_boot", {"boot_id": UUID(int=1)}, "failed", "same_boot_id_changed_time"),
    ("next_boot", {"host_id": "another-host"}, "failed", "host_mismatch"),
    ("next_boot", {"started_at": _time(20)}, "failed", "invalid_observation_order"),
    ("armed", {"deadline": _time(20)}, "failed", "invalid_observation_order"),
    ("armed", {"execution_started_at": _time(-1)}, "failed", "invalid_observation_order"),
    ("post_boot", {"captured_at": _time(25)}, "failed", "invalid_observation_order"),
    ("post_boot", {"run_id": "other-run"}, "failed", "run_mismatch"),
    ("post_boot", {"active_worker": None}, "failed", "inconsistent_worker_state"),
    ("post_boot", {"audit_chain_verified": False}, "inconclusive", "audit_unverified"),
    ("post_boot", {"armed_execution_recorded": False}, "inconclusive", "audit_unverified"),
    ("post_boot", {"armed_operation_terminal": None}, "inconclusive", "audit_unverified"),
    ("post_boot", {"armed_operation_terminal": True}, "failed", "terminal_before_recovery"),
    ("post_boot", {"surviving_worker": None}, "inconclusive", "container_observation_missing"),
    ("post_boot", {"surviving_worker": True}, "failed", "container_survived"),
    ("post_boot", {"remaining_actions": 29}, "failed", "budget_changed"),
    ("recovery", {"boot_id": UUID(int=3)}, "failed", "recovery_boot_mismatch"),
    ("repeated_recovery", {"boot_id": UUID(int=3)}, "failed", "recovery_boot_mismatch"),
    ("recovery", {"audit_continuity_verified": False}, "inconclusive", "recovery_continuity_unverified"),
    ("repeated_recovery", {"audit_continuity_verified": False}, "inconclusive", "recovery_continuity_unverified"),
    ("recovery", {"worker_teardown": "not_running"}, "failed", "recovery_state_unexpected"),
    ("repeated_recovery", {"captured_at": _time(40)}, "failed", "invalid_observation_order"),
    ("repeated_recovery", {"worker_teardown": "confirmed"}, "failed", "recovery_state_unexpected"),
    ("repeated_recovery", {"remaining_actions": 27}, "failed", "budget_changed"),
])
def test_incomplete_and_contradictory_evidence_cannot_pass(complete, section, changed, status, reason):
    replacement = getattr(complete, section).model_copy(update=changed)
    verdict = classify_reboot_evidence(complete.model_copy(update={section: replacement}))
    assert (verdict.status, verdict.reason) == (status, reason)


def test_two_recovery_observations_are_required(complete):
    verdict = classify_reboot_evidence(complete.model_copy(update={"repeated_recovery": None}))
    assert (verdict.status, verdict.reason) == ("inconclusive", "recovery_missing")


def test_schema_rejects_forged_model_value_and_naive_timestamp(complete):
    fake_budget = complete.post_boot.model_copy(update={"remaining_actions": True})
    with pytest.raises(ValidationError):
        classify_reboot_evidence(complete.model_copy(update={"post_boot": fake_budget}))
    naive = complete.armed.model_copy(update={"captured_at": datetime(2026, 11, 19)})
    with pytest.raises(ValidationError):
        classify_reboot_evidence(complete.model_copy(update={"armed": naive}))


@pytest.mark.parametrize("section", ["recovery", "repeated_recovery"])
@pytest.mark.parametrize("changed", [
    {"run_id": "another-run"}, {"worker_id": "successor"}, {"operation_id": "operation-two"},
])
def test_recovery_observation_cannot_be_spliced_from_other_worker_or_operation(complete, section, changed):
    observation = getattr(complete, section)
    worker = complete.armed.worker.model_copy(update=changed)
    replacement = observation.model_copy(update={"worker": worker})
    verdict = classify_reboot_evidence(complete.model_copy(update={section: replacement}))
    assert (verdict.status, verdict.reason) == ("failed", "recovery_worker_mismatch")


def test_zero_remaining_actions_is_incompatible_with_planning_recovery(complete):
    sections = ("armed", "post_boot", "recovery", "repeated_recovery")
    exhausted = complete.model_copy(update={
        name: getattr(complete, name).model_copy(update={"remaining_actions": 0}) for name in sections
    })
    verdict = classify_reboot_evidence(exhausted)
    assert (verdict.status, verdict.reason) == ("failed", "planning_budget_exhausted")
