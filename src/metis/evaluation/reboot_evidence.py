"""Classify normalized host-reboot observations without operating on the host."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")]
BudgetBalance = Annotated[int, Field(ge=0)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class BootObservation(_Record):
    host_id: Identifier
    boot_id: UUID
    started_at: AwareDatetime


class WorkerIdentity(_Record):
    run_id: Identifier
    worker_id: Identifier
    operation_id: Identifier


class ArmedObservation(_Record):
    captured_at: AwareDatetime
    worker: WorkerIdentity
    execution_started_at: AwareDatetime
    deadline: AwareDatetime
    remaining_actions: BudgetBalance
    remaining_seconds: BudgetBalance


class PostBootObservation(_Record):
    captured_at: AwareDatetime
    run_id: Identifier
    run_state: Literal["executing", "planning", "other"]
    active_worker: WorkerIdentity | None
    remaining_actions: BudgetBalance
    remaining_seconds: BudgetBalance
    surviving_worker: bool | None
    audit_chain_verified: bool
    armed_execution_recorded: bool | None
    armed_operation_terminal: bool | None


class RecoveryObservation(_Record):
    captured_at: AwareDatetime
    boot_id: UUID
    worker: WorkerIdentity
    audit_continuity_verified: bool
    run_state: Literal["planning", "executing", "other"]
    worker_teardown: Literal["confirmed", "not_running", "unconfirmed"]
    remaining_actions: BudgetBalance
    remaining_seconds: BudgetBalance


class RebootEvidence(_Record):
    previous_boot: BootObservation
    armed: ArmedObservation
    next_boot: BootObservation
    post_boot: PostBootObservation
    recovery: RecoveryObservation | None = None
    repeated_recovery: RecoveryObservation | None = None


class RebootVerdict(_Record):
    status: Literal["passed", "inconclusive", "failed"]
    reason: Literal[
        "same_worker_recovered", "boot_unchanged", "same_boot_id_changed_time", "host_mismatch",
        "invalid_observation_order", "arm_expired", "worker_missing", "worker_changed",
        "audit_unverified", "terminal_before_recovery", "container_observation_missing",
        "container_survived", "recovery_missing", "run_mismatch", "inconsistent_worker_state",
        "budget_changed", "recovery_state_unexpected", "planning_budget_exhausted",
        "recovery_boot_mismatch", "recovery_worker_mismatch", "recovery_continuity_unverified",
        "time_budget_increased",
    ]


def classify_reboot_evidence(evidence: RebootEvidence) -> RebootVerdict:
    """Check the same-worker recovery gate on trusted, normalized observations."""
    evidence = RebootEvidence.model_validate(evidence)
    previous, next_boot = evidence.previous_boot, evidence.next_boot
    armed, post = evidence.armed, evidence.post_boot
    if previous.host_id != next_boot.host_id:
        return RebootVerdict(status="failed", reason="host_mismatch")
    if previous.boot_id == next_boot.boot_id:
        if previous.started_at != next_boot.started_at:
            return RebootVerdict(status="failed", reason="same_boot_id_changed_time")
        return RebootVerdict(status="inconclusive", reason="boot_unchanged")
    if not previous.started_at <= armed.execution_started_at <= armed.captured_at < next_boot.started_at <= post.captured_at:
        return RebootVerdict(status="failed", reason="invalid_observation_order")
    if armed.deadline <= armed.captured_at:
        return RebootVerdict(status="failed", reason="invalid_observation_order")
    if post.run_id != armed.worker.run_id or (post.active_worker is not None and post.active_worker.run_id != post.run_id):
        return RebootVerdict(status="failed", reason="run_mismatch")
    if (post.run_state == "executing") != (post.active_worker is not None):
        return RebootVerdict(status="failed", reason="inconsistent_worker_state")
    if armed.deadline <= next_boot.started_at:
        return RebootVerdict(status="inconclusive", reason="arm_expired")
    if post.active_worker is None:
        return RebootVerdict(status="inconclusive", reason="worker_missing")
    if post.active_worker != armed.worker:
        return RebootVerdict(status="inconclusive", reason="worker_changed")
    if (not post.audit_chain_verified or post.armed_execution_recorded is not True
            or post.armed_operation_terminal is None):
        return RebootVerdict(status="inconclusive", reason="audit_unverified")
    if post.armed_operation_terminal:
        return RebootVerdict(status="failed", reason="terminal_before_recovery")
    if post.surviving_worker is None:
        return RebootVerdict(status="inconclusive", reason="container_observation_missing")
    if post.surviving_worker:
        return RebootVerdict(status="failed", reason="container_survived")
    if post.remaining_actions != armed.remaining_actions:
        return RebootVerdict(status="failed", reason="budget_changed")

    recovery, repeated = evidence.recovery, evidence.repeated_recovery
    if recovery is None or repeated is None:
        return RebootVerdict(status="inconclusive", reason="recovery_missing")
    if not post.captured_at < recovery.captured_at < repeated.captured_at:
        return RebootVerdict(status="failed", reason="invalid_observation_order")
    if recovery.boot_id != next_boot.boot_id or repeated.boot_id != next_boot.boot_id:
        return RebootVerdict(status="failed", reason="recovery_boot_mismatch")
    if recovery.worker != armed.worker or repeated.worker != armed.worker:
        return RebootVerdict(status="failed", reason="recovery_worker_mismatch")
    if not recovery.audit_continuity_verified or not repeated.audit_continuity_verified:
        return RebootVerdict(status="inconclusive", reason="recovery_continuity_unverified")
    if recovery.remaining_actions != post.remaining_actions or repeated.remaining_actions != post.remaining_actions:
        return RebootVerdict(status="failed", reason="budget_changed")
    if not armed.remaining_seconds >= post.remaining_seconds >= recovery.remaining_seconds >= repeated.remaining_seconds:
        return RebootVerdict(status="failed", reason="time_budget_increased")
    if post.remaining_actions == 0 or repeated.remaining_seconds == 0:
        return RebootVerdict(status="failed", reason="planning_budget_exhausted")
    if (recovery.run_state, recovery.worker_teardown, repeated.run_state, repeated.worker_teardown) != (
        "planning", "confirmed", "planning", "not_running",
    ):
        return RebootVerdict(status="failed", reason="recovery_state_unexpected")
    return RebootVerdict(status="passed", reason="same_worker_recovered")
