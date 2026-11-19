"""Dry-run admission and pre-invocation receipts for the synthetic Issue #6 pilot.

A trusted operator provisions a single private ledger and registers approval in
it. The rehearsal process may claim it once. No receipt is executable authority
and this module has no subprocess or model adapter.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.core.agent_scheduler import AgentScheduler

CASE_COUNT = 36
MAX_CALLS = 72
PHASE_SECONDS = 60
COHORT_SECONDS = 72 * 60

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@+-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Phase = Literal[1, 2]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class FrozenCase(_Record):
    case_id: Identifier
    artifact_hmac: Digest


class DryRunApproval(_Record):
    approval_id: Identifier
    mode: Literal["dry_run"]
    source_sha256: Digest
    protocol_sha256: Digest
    runtime_sha256: Digest
    workspace_sha256: Digest
    model: Identifier
    phase_schema_sha256: tuple[Digest, Digest]
    expires_at: Annotated[int, Field(gt=0)]
    cases: Annotated[tuple[FrozenCase, ...], Field(min_length=CASE_COUNT, max_length=CASE_COUNT)]

    @model_validator(mode="after")
    def distinct_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != CASE_COUNT:
            raise ValueError("case IDs must be distinct")
        if len({case.artifact_hmac for case in self.cases}) != CASE_COUNT:
            raise ValueError("artifact commitments must be distinct")
        return self


class DryRunPhase(_Record):
    case_id: Identifier
    phase: Phase
    artifact_hmac: Digest
    prompt_hmac: Digest
    schema_sha256: Digest

    @field_validator("phase", mode="before")
    @classmethod
    def require_exact_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("phase must be an integer")
        return value


def workspace_binding(workspace: Path) -> str:
    return hashlib.sha256(bytes(workspace.resolve())).hexdigest()


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS issue6_dry_approvals (
        approval_id TEXT PRIMARY KEY,
        binding TEXT NOT NULL,
        claimed INTEGER NOT NULL DEFAULT 0 CHECK (claimed IN (0, 1))
    )""",
    """CREATE TABLE IF NOT EXISTS issue6_dry_reservations (
        reservation_id INTEGER PRIMARY KEY REFERENCES agent_turn_reservations(id),
        approval_id TEXT NOT NULL REFERENCES issue6_dry_approvals(approval_id),
        case_index INTEGER NOT NULL CHECK (case_index >= 0 AND case_index < 36),
        phase INTEGER NOT NULL CHECK (phase IN (1, 2)),
        commitment TEXT NOT NULL,
        UNIQUE (approval_id, case_index, phase)
    )""",
)


@dataclass(frozen=True)
class CanaryWindow:
    database: Path
    monotonic_cutoff: float
    wall_cutoff: float


class DryRunAdmission:
    """Bind each approval to the canonical scheduler database for this study."""

    def __init__(self, scheduler: AgentScheduler, *,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time):
        self._scheduler = scheduler
        self._database = scheduler.database.resolve(strict=True)
        self._clock = clock
        self._wall_clock = wall_clock
        self._approval: DryRunApproval | None = None
        self._cutoff = 0.0
        self._phase_cutoffs: dict[tuple[str, int], float] = {}
        with closing(sqlite3.connect(self._database)) as db, db:
            for statement in _SCHEMA:
                db.execute(statement)

    def register(self, approval: DryRunApproval) -> None:
        """Provision approval from the trusted operator in the private ledger."""
        approval = DryRunApproval.model_validate(approval)
        with closing(sqlite3.connect(self._database)) as db, db:
            db.execute("INSERT INTO issue6_dry_approvals (approval_id, binding) VALUES (?, ?)",
                       (approval.approval_id, approval.model_dump_json()))

    def claim(self, approval: DryRunApproval, workspace: Path) -> None:
        """Compare the exact registered study and consume approval without a resume path."""
        approval = DryRunApproval.model_validate(approval)
        if self._approval is not None or approval.workspace_sha256 != workspace_binding(workspace):
            raise ValueError("dry-run workspace or controller does not match approval")
        with closing(sqlite3.connect(self._database)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            clock = self._clock()
            wall_clock = self._wall_clock()
            remaining = approval.expires_at - wall_clock
            if not math.isfinite(clock) or not math.isfinite(remaining) or remaining <= 0:
                raise ValueError("dry-run approval expired or clock unavailable")
            updated = db.execute(
                "UPDATE issue6_dry_approvals SET claimed=1 WHERE approval_id=? AND binding=? AND claimed=0",
                (approval.approval_id, approval.model_dump_json()),
            )
            if updated.rowcount != 1:
                raise ValueError("dry-run approval was not registered, mismatches, or was already consumed")
        self._cutoff = clock + min(COHORT_SECONDS, remaining)
        self._approval = approval

    def open_phase(self, case_id: str, phase: Phase) -> None:
        """Start the phase clock before handoff/receipt preparation, without extensions."""
        self._case_index(case_id)
        if type(phase) is not int or phase not in (1, 2):
            raise ValueError("invalid dry-run phase")
        now = self._clock()
        if not math.isfinite(now) or now >= self._cutoff:
            raise ValueError("dry-run cohort deadline reached")
        self._phase_cutoffs.setdefault((case_id, phase), min(self._cutoff, now + PHASE_SECONDS))

    def canary_window(self, workspace: Path, receipt: DryRunPhase) -> CanaryWindow:
        """Return the frozen process-time bounds for the open dry-run phase."""
        receipt = DryRunPhase.model_validate(receipt)
        approval = self._approval
        if approval is None or workspace_binding(workspace) != approval.workspace_sha256:
            raise ValueError("canary workspace does not match the claimed dry-run approval")
        cutoff = self._phase_cutoffs.get((receipt.case_id, receipt.phase))
        if cutoff is None:
            raise ValueError("dry-run phase was not opened")
        return CanaryWindow(self._database, cutoff, approval.expires_at)

    def _case_index(self, case_id: str) -> int:
        if self._approval is not None:
            for i, case in enumerate(self._approval.cases):
                if case.case_id == case_id:
                    return i
        raise ValueError("dry-run case does not belong to the claimed cohort")

    def reserve_phase(self, run_id: str, assignment_id: str, attempt_id: str,
                      receipt: DryRunPhase) -> int:
        """Commit a scheduler charge and its dry-run receipt as a single write."""
        receipt = DryRunPhase.model_validate(receipt)
        case_index = self._case_index(receipt.case_id)
        approval = self._approval
        assert approval is not None
        if receipt.artifact_hmac != approval.cases[case_index].artifact_hmac:
            raise ValueError("artifact receipt differs from frozen dry-run case")
        if receipt.schema_sha256 != approval.phase_schema_sha256[receipt.phase - 1]:
            raise ValueError("schema receipt differs from frozen dry-run phase")
        cutoff = self._phase_cutoffs.get((receipt.case_id, receipt.phase))
        if cutoff is None:
            raise ValueError("dry-run phase was not opened")

        if self._scheduler.database.resolve(strict=True) != self._database:
            raise ValueError("scheduler database differs from the dry-run ledger")

        def verify_expiry() -> None:
            wall_now = self._wall_clock()
            if not math.isfinite(wall_now) or wall_now >= approval.expires_at:
                raise ValueError("dry-run approval expired or clock unavailable")

        def validate(db: sqlite3.Connection) -> None:
            main_path = next(path for _, name, path in db.execute("PRAGMA database_list") if name == "main")
            if Path(main_path) != self._database:
                raise ValueError("reservation database differs from the dry-run ledger")
            claimed = db.execute(
                "SELECT binding, claimed FROM issue6_dry_approvals WHERE approval_id=?",
                (approval.approval_id,),
            ).fetchone()
            if claimed != (approval.model_dump_json(), 1):
                raise ValueError("claimed approval does not match in the reservation database")
            verify_expiry()

        def persist(db: sqlite3.Connection, reservation: int) -> None:
            verify_expiry()
            now = self._clock()
            if not math.isfinite(now) or now >= cutoff:
                raise ValueError("dry-run phase deadline reached")
            self._append(db, approval, case_index, receipt, reservation, run_id, assignment_id)

        reserved = self._scheduler.reserve_model_turn(
            run_id, assignment_id, attempt_id, validate_reservation=validate, persist_receipt=persist,
        )
        if reserved is None:
            raise ValueError("scheduler model-turn budget exhausted")
        return reserved["reservation_id"]

    @staticmethod
    def _append(db: sqlite3.Connection, approval: DryRunApproval, case_index: int,
                receipt: DryRunPhase, reservation: int, run_id: str, assignment_id: str) -> None:
        # The scheduler transaction already serializes reservations in this database.
        model_and_budget = db.execute("""
            SELECT json_extract(j.model, '$.model'), b.turn_limit, b.turns_reserved
            FROM agent_jobs j JOIN agent_run_turn_budgets b ON b.run_id = j.run_id
            WHERE j.assignment_id = ?
        """, (assignment_id,)).fetchone()
        if model_and_budget != (approval.model, 2, receipt.phase):
            raise ValueError("scheduler model or phase budget differs from dry-run approval")
        previous = db.execute("""
            SELECT r.case_index, r.phase, t.run_id, j.state
            FROM issue6_dry_reservations r
            JOIN agent_turn_reservations t ON t.id = r.reservation_id
            JOIN agent_jobs j ON j.assignment_id = t.assignment_id
                AND j.attempt_id = t.attempt_id AND j.run_id = t.run_id
            WHERE r.approval_id = ? ORDER BY r.reservation_id DESC LIMIT 1
        """, (approval.approval_id,)).fetchone()
        count, = db.execute("SELECT COUNT(*) FROM issue6_dry_reservations WHERE approval_id=?",
                            (approval.approval_id,)).fetchone()
        if count >= MAX_CALLS:
            raise ValueError("dry-run cohort call budget exhausted")
        if receipt.phase == 1:
            if previous is None:
                allowed = case_index == 0
            else:
                index, phase, prior_run, terminal = previous
                allowed = (
                    case_index == index + 1 and prior_run != run_id
                    and (terminal in {"failed", "timed_out"} or (phase == 2 and terminal == "completed"))
                )
        else:
            allowed = previous == (case_index, 1, run_id, "completed")
        if not allowed:
            raise ValueError("dry-run reservation is out of order or the prior handoff is unresolved")
        db.execute("INSERT INTO issue6_dry_reservations VALUES (?, ?, ?, ?, ?)",
                   (reservation, approval.approval_id, case_index, receipt.phase, receipt.model_dump_json()))
