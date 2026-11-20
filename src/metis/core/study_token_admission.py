"""Persistent token allowances for a trusted study controller.

The native runtime must independently enforce each allowance before doing any
model work. Admission alone does not make a runner hard-cap capable.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metis.core.token_reservation import FULL_CONTEXT_RESERVATION_TOKENS

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@+-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Tokens = Annotated[int, Field(ge=1, le=10_000_000)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class StudyTokenPin(_Record):
    study_id: Identifier
    protocol_sha256: Digest
    runtime_sha256: Digest
    model_sha256: Digest
    token_limit: Tokens
    native_manifest_sha256: Digest | None = None


class SlotTokenPin(_Record):
    run_id: Identifier
    task_id: Identifier
    repetition: Annotated[int, Field(ge=0, lt=20)]
    arm: Identifier
    token_limit: Tokens


class TokenAttempt(_Record):
    assignment_id: Identifier
    attempt_id: Identifier
    turn_reservation_id: Annotated[int, Field(ge=1, le=2**63 - 1)]
    prompt_sha256: Digest
    tokens: Tokens


class TokenAdmissionReceipt(_Record):
    study: StudyTokenPin
    slot: SlotTokenPin
    attempt: TokenAttempt


class TokenLaunchClaim(_Record):
    receipt: TokenAdmissionReceipt
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class TokenLaunchOutcome(_Record):
    status: Literal[
        "completed", "cap_denied", "unsupported_graph", "server_error",
        "launch_failed", "receipt_invalid", "timeout", "cancelled", "lost",
    ]
    exit_status: Annotated[int, Field(ge=-127, le=255)] | None = None
    observed_work: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    native_manifest_sha256: Digest | None = None

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        if self.status == "completed":
            valid = self.exit_status == 0 and self.observed_work is not None
        elif self.status in ("cap_denied", "unsupported_graph"):
            valid = self.exit_status == 75 and self.observed_work is not None
        elif self.status == "server_error":
            valid = (self.observed_work is None if self.exit_status is None else
                     1 <= self.exit_status <= 255 and self.exit_status not in (74, 75)
                     and self.observed_work is not None)
        else:
            valid = self.observed_work is None and (
                self.status not in ("launch_failed", "lost") or self.exit_status is None
            )
        if not valid:
            raise ValueError("terminal observations do not match outcome")
        return self


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS study_token_pins (
        study_id TEXT PRIMARY KEY, protocol_sha256 TEXT NOT NULL UNIQUE,
        runtime_sha256 TEXT NOT NULL, model_sha256 TEXT NOT NULL, token_limit INTEGER NOT NULL,
        native_manifest_sha256 TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_slots (
        run_id TEXT PRIMARY KEY, study_id TEXT NOT NULL, task_id TEXT NOT NULL,
        repetition INTEGER NOT NULL, arm TEXT NOT NULL, token_limit INTEGER NOT NULL,
        UNIQUE (study_id, task_id, repetition, arm),
        UNIQUE (study_id, run_id),
        FOREIGN KEY (study_id) REFERENCES study_token_pins(study_id)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_attempts (
        study_id TEXT NOT NULL, run_id TEXT NOT NULL, turn_reservation_id INTEGER NOT NULL,
        assignment_id TEXT NOT NULL, attempt_id TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
        tokens INTEGER NOT NULL CHECK (tokens > 0),
        PRIMARY KEY (run_id, turn_reservation_id),
        FOREIGN KEY (study_id, run_id) REFERENCES study_token_slots(study_id, run_id)
    )""",
    """CREATE INDEX IF NOT EXISTS study_token_attempts_by_study ON study_token_attempts(study_id)""",
    """CREATE TABLE IF NOT EXISTS study_token_launches (
        run_id TEXT NOT NULL, turn_reservation_id INTEGER NOT NULL, nonce TEXT NOT NULL UNIQUE,
        consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1)),
        launched INTEGER NOT NULL DEFAULT 0 CHECK (launched IN (0, 1)),
        launch_owner TEXT,
        PRIMARY KEY (run_id, turn_reservation_id),
        FOREIGN KEY (run_id, turn_reservation_id)
            REFERENCES study_token_attempts(run_id, turn_reservation_id)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_outcomes (
        nonce TEXT PRIMARY KEY NOT NULL,
        status TEXT NOT NULL, exit_status INTEGER, observed_work INTEGER,
        native_manifest_sha256 TEXT,
        FOREIGN KEY (nonce) REFERENCES study_token_launches(nonce)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_fixture_claims (
        nonce TEXT PRIMARY KEY NOT NULL,
        FOREIGN KEY (nonce) REFERENCES study_token_launches(nonce)
    )""",
)


_COLUMN_MIGRATIONS = (
    ("study_token_pins", "native_manifest_sha256",
     "ALTER TABLE study_token_pins ADD COLUMN native_manifest_sha256 TEXT"),
    ("study_token_outcomes", "native_manifest_sha256",
     "ALTER TABLE study_token_outcomes ADD COLUMN native_manifest_sha256 TEXT"),
    ("study_token_launches", "consumed",
     ("ALTER TABLE study_token_launches ADD COLUMN consumed INTEGER NOT NULL DEFAULT 0 "
      "CHECK (consumed IN (0, 1))")),
    ("study_token_launches", "launched",
     ("ALTER TABLE study_token_launches ADD COLUMN launched INTEGER NOT NULL DEFAULT 0 "
      "CHECK (launched IN (0, 1))")),
    ("study_token_launches", "launch_owner",
     "ALTER TABLE study_token_launches ADD COLUMN launch_owner TEXT"),
)


def _ensure_schema(db: sqlite3.Connection) -> None:
    for statement in _SCHEMA:
        db.execute(statement)
    # Legacy reservations stay charged and unpinned; this migration cannot
    # promote them into a held-out native launch. Existing launch claims are
    # marked consumed so migration cannot make an old claim launchable again.
    for table, column, statement in _COLUMN_MIGRATIONS:
        if db.execute(
            "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (table, column),
        ).fetchone() is None:
            db.execute(statement)
            if table == "study_token_launches":
                db.execute("UPDATE study_token_launches SET consumed=1")
                if column == "launched":
                    db.execute("UPDATE study_token_launches SET launched=1")

_fixture_fd_guard = Lock()
_fixture_lock_fds: set[int] = set()


def _after_fixture_fork() -> None:
    for fd in _fixture_lock_fds:
        os.close(fd)
    _fixture_lock_fds.clear()
    _fixture_fd_guard.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_fixture_fd_guard.acquire,
        after_in_parent=_fixture_fd_guard.release,
        after_in_child=_after_fixture_fork,
    )


class FixtureClaimBusy(ValueError):
    """A fixture controller or reconciler still holds the claim lock."""


class SchedulerLaunchDeadlineExpired(ValueError):
    """The persisted scheduler or run deadline elapsed before claim consumption."""


class StudyTokenAdmission:
    """Atomically charge both ceilings from append-only receipts.

    Generic ``reserve`` remains available for isolated fixture controllers.
    Held-out launches should use ``reserve_and_claim_scheduler_turn`` so their
    pins and one-time claim are derived from the committed held-out binding and
    the scheduler's live reservation in the same SQLite transaction.
    """

    def __init__(self, database: Path):
        self.database = database.resolve()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            db.execute("BEGIN IMMEDIATE")
            _ensure_schema(db)
            yield db

    def reserve_and_claim_scheduler_turn(
        self, db: sqlite3.Connection, *, run_id: str, assignment_id: str, attempt_id: str,
        reservation_id: int, prompt: str,
    ) -> TokenLaunchClaim:
        """Atomically charge and claim the current bound held-out scheduler turn.

        Call only from ``AgentScheduler.reserve_model_turn``'s ``persist_receipt``
        callback. The caller must use this ledger's database for that scheduler.
        All identities, limits and pins are read from the same SQLite transaction;
        only the exact rendered prompt is supplied, and only its digest is stored.
        The per-call amount is a conservative reservation of the configured
        native context plus the committed output allowance. The runner must tokenize
        and reject prompts above that context before completion. It is not
        measured usage or proof of a provider hard cap.
        """
        if not db.in_transaction:
            raise ValueError("scheduler admission requires the active reservation transaction")
        if (db.execute("PRAGMA foreign_keys").fetchone()[0] != 1
                or db.execute("PRAGMA synchronous").fetchone()[0] != 2):
            raise ValueError("scheduler admission connection lacks durable foreign-key enforcement")
        if (type(reservation_id) is not int or reservation_id < 1
                or not isinstance(prompt, str) or not prompt.strip()):
            raise ValueError("invalid scheduler admission input")
        prompt_bytes = prompt.encode("utf-8")
        if len(prompt_bytes) > 65_536:
            raise ValueError("held-out prompt exceeds admission boundary")
        _ensure_schema(db)

        binding_row = db.execute(
            "SELECT payload FROM heldout_arm_bindings WHERE run_id=?", (run_id,),
        ).fetchone()
        if binding_row is None or not isinstance(binding_row[0], str) or len(binding_row[0]) > 16_384:
            raise ValueError("held-out admission binding unavailable")
        try:
            binding = json.loads(binding_row[0])
        except (TypeError, json.JSONDecodeError):
            raise ValueError("held-out admission binding unavailable") from None
        if (not isinstance(binding, dict) or binding.get("measurement") != "real_model"
                or not isinstance(binding.get("study_id"), str)):
            raise ValueError("held-out admission requires a committed real-model binding")
        self._require_active_run_state(db, run_id)
        if (not isinstance(binding.get("protocol_sha256"), str)
                or len(binding["protocol_sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in binding["protocol_sha256"])):
            raise ValueError("held-out protocol commitment unavailable")

        from metis.evaluation.heldout_analysis import Budget
        from metis.evaluation.heldout_protocol import ArmConfig, LlamaBackendPin

        try:
            backend = LlamaBackendPin.model_validate(binding["llama_backend"])
            config = ArmConfig.model_validate(binding["arm_config"])
            budget = Budget.model_validate(binding["budget"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("held-out admission pins unavailable") from None
        if (backend.native_manifest_sha256 is None or not backend.context_reservation
                or backend.database_path != str(self.database)
                or binding.get("model_pin") is None or binding.get("runtime_pin") is None):
            raise ValueError("held-out native manifest or database pin unavailable")
        if (not isinstance(binding.get("task_id"), str)
                or type(binding.get("repetition")) is not int
                or binding.get("arm") not in {"full", "without_memory", "without_planner", "single_agent"}):
            raise ValueError("held-out slot binding unavailable")
        prefix = binding.get("prompt_text")
        memory_digests = binding.get("memory_card_digests")
        if not isinstance(prefix, str) or not isinstance(memory_digests, list):
            raise ValueError("held-out prompt or memory binding unavailable")  # noqa: TRY004 -- invalid persisted binding
        from metis.core.codex_specialist import final_handoff_schema
        from metis.core.llama_specialist import LlamaSpecialist
        bound_assignment = prefix + "\n\n"
        if not any(prompt.startswith(LlamaSpecialist.native_request_prefix(schema) + bound_assignment)
                   for schema in (None, final_handoff_schema())):
            raise ValueError("rendered prompt does not use the bound held-out prefix")
        prefix_digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
        if prefix_digest != config.prompt_sha256:
            raise ValueError("held-out prompt prefix digest mismatch")

        session = db.execute(
            "SELECT evaluation_split,max_actions,wall_seconds FROM codex_sessions WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if (session is None or session[0] != "heldout" or type(session[1]) is not int
                or not isinstance(session[2], (int, float))
                or session[1] > budget.actions or session[2] > budget.seconds):
            raise ValueError("held-out session does not match its committed budget")
        job = db.execute(
            "SELECT run_id,state,attempt_id,host,model FROM agent_jobs WHERE assignment_id=?",
            (assignment_id,),
        ).fetchone()
        if job is None or job[:3] != (run_id, "running", attempt_id):
            raise ValueError("scheduler assignment is not the current running attempt")
        try:
            model = json.loads(job[4]) if isinstance(job[4], str) else None
        except json.JSONDecodeError:
            model = None
        if (not isinstance(model, dict) or model.get("model") != binding["model_pin"]
                or job[3] != binding["runtime_pin"]):
            raise ValueError("scheduler model or runtime differs from the held-out binding")
        reservation = db.execute(
            "SELECT run_id,assignment_id,attempt_id FROM agent_turn_reservations WHERE id=?",
            (reservation_id,),
        ).fetchone()
        if reservation != (run_id, assignment_id, attempt_id):
            raise ValueError("scheduler turn reservation does not match the running attempt")
        arm_events = db.execute(
            "SELECT detail FROM agent_job_log WHERE assignment_id=? AND attempt_id=? "
            "AND event='heldout_arm_applied'", (assignment_id, attempt_id),
        ).fetchall()
        expected_arm_event = {
            "protocol_sha256": binding["protocol_sha256"], "arm": binding["arm"],
            "memory_cards": len(memory_digests) if config.memory_enabled else 0,
            "model": binding["model_pin"], "runtime": binding["runtime_pin"],
        }
        if len(arm_events) != 1:
            raise ValueError("held-out arm dispatch evidence unavailable")
        try:
            actual_arm_event = json.loads(arm_events[0][0])
        except (TypeError, json.JSONDecodeError):
            raise ValueError("held-out arm dispatch evidence unavailable") from None
        if not isinstance(actual_arm_event, dict) or actual_arm_event != expected_arm_event:
            raise ValueError("held-out arm dispatch evidence mismatch")

        # The native runner must reject an oversized tokenized prompt before
        # completion when this full-context reservation is enabled.
        amount = FULL_CONTEXT_RESERVATION_TOKENS + backend.max_output_tokens
        if amount > budget.tokens or amount > backend.token_limit:
            raise ValueError("native per-call reservation exceeds held-out token cap")
        receipt = TokenAdmissionReceipt(
            study=StudyTokenPin(
                study_id=binding["study_id"],
                protocol_sha256=binding["protocol_sha256"],
                runtime_sha256=backend.binary_sha256,
                model_sha256=backend.model_sha256,
                token_limit=backend.token_limit,
                native_manifest_sha256=backend.native_manifest_sha256,
            ),
            slot=SlotTokenPin(
                run_id=run_id, task_id=binding["task_id"], repetition=binding["repetition"],
                arm=binding["arm"], token_limit=budget.tokens,
            ),
            attempt=TokenAttempt(
                assignment_id=assignment_id, attempt_id=attempt_id,
                turn_reservation_id=reservation_id,
                prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(), tokens=amount,
            ),
        )
        self._reserve_in_transaction(db, receipt)
        claim = TokenLaunchClaim(receipt=receipt, nonce=secrets.token_hex(16))
        inserted = db.execute(
            "INSERT INTO study_token_launches(run_id,turn_reservation_id,nonce) VALUES(?,?,?) "
            "ON CONFLICT DO NOTHING",
            (run_id, reservation_id, claim.nonce),
        )
        if inserted.rowcount != 1:
            raise ValueError("scheduler turn already has a launch claim")
        detail = {
            "reservation_id": reservation_id,
            "prefix_sha256": prefix_digest,
            "prompt_sha256": receipt.attempt.prompt_sha256,
            "model": binding["model_pin"], "runtime": binding["runtime_pin"],
        }
        db.execute(
            "INSERT INTO agent_job_log(assignment_id,attempt_id,event,detail,time) VALUES(?,?,?,?,?)",
            (assignment_id, attempt_id, "heldout_prompt_applied", json.dumps(detail, sort_keys=True), time.time()),
        )
        return claim

    def consume_launch_claim(self, claim: TokenLaunchClaim) -> None:
        """Atomically validate the persisted receipt and consume its claim once.

        The native fixture controller calls this after staging and preflight.
        A copied or replayed claim cannot start a second admitted invocation.
        """
        self._consume_launch_claim(claim, scheduler_bound=False)

    def consume_scheduler_launch_claim(self, claim: TokenLaunchClaim) -> None:
        """Consume a scheduler-bound claim only while its job and reservation remain live."""
        self._consume_launch_claim(claim, scheduler_bound=True)

    def validate_consumed_scheduler_launch_claim(self, claim: TokenLaunchClaim) -> None:
        """Revalidate a consumed claim at the native consumer boundary."""
        value = TokenLaunchClaim.model_validate(claim)
        receipt = value.receipt
        with self._transaction() as db:
            self._require_current_scheduler_turn(db, receipt)
            self._require_committed_receipt(db, receipt)
            stored = db.execute(
                "SELECT l.nonce,l.consumed,l.launched,o.nonce FROM study_token_launches AS l "
                "LEFT JOIN study_token_outcomes AS o ON o.nonce=l.nonce "
                "WHERE l.run_id=? AND l.turn_reservation_id=?",
                (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
            ).fetchone()
            if stored != (value.nonce, 1, 0, None):
                raise ValueError("scheduler launch claim is not consumed")

    def claim_scheduler_native_launch(self, claim: TokenLaunchClaim, *, owner_id: str) -> Literal[
        "claimed", "stale", "already_started",
    ]:
        """Atomically fence a consumed claim to one native consumer invocation."""
        if not re.fullmatch(r"[0-9a-f]{32}", owner_id):
            raise ValueError("invalid native launch owner")
        value = TokenLaunchClaim.model_validate(claim)
        receipt = value.receipt
        with self._transaction() as db:
            self._require_committed_receipt(db, receipt)
            slot, attempt = receipt.slot, receipt.attempt
            stored = db.execute(
                "SELECT l.nonce,l.consumed,l.launched,l.launch_owner,o.nonce FROM study_token_launches AS l "
                "LEFT JOIN study_token_outcomes AS o ON o.nonce=l.nonce "
                "WHERE l.run_id=? AND l.turn_reservation_id=?",
                (slot.run_id, attempt.turn_reservation_id),
            ).fetchone()
            if stored is None or stored[0] != value.nonce or stored[1] != 1:
                raise ValueError("scheduler launch claim is invalid or unconsumed")
            if stored[2] == 1:
                if stored[3] != owner_id or stored[4] is not None:
                    return "already_started"
                try:
                    self._require_current_scheduler_turn(db, receipt)
                except ValueError:
                    return "stale"
                return "claimed"
            if stored[4] is not None:
                return "already_started"
            stale = False
            try:
                self._require_current_scheduler_turn(db, receipt)
            except ValueError:
                stale = True
            changed = db.execute(
                "UPDATE study_token_launches SET launched=1,launch_owner=? WHERE run_id=? "
                "AND turn_reservation_id=? AND nonce=? AND consumed=1 AND launched=0",
                (owner_id, slot.run_id, attempt.turn_reservation_id, value.nonce),
            )
            if changed.rowcount != 1:
                return "already_started"
            return "stale" if stale else "claimed"

    def is_consumed_scheduler_launch_claim(self, claim: TokenLaunchClaim) -> bool:
        """Check exact persisted consumption even if the scheduler has since stopped."""
        value = TokenLaunchClaim.model_validate(claim)
        receipt = value.receipt
        try:
            # This is a read-only check: do not take BEGIN IMMEDIATE here, or
            # concurrent scheduler writes could turn a valid consumed claim
            # into a false negative and lose its terminal accounting.
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro",
                                         uri=True, timeout=5)) as db:
                self._require_committed_receipt(db, receipt)
                stored = db.execute(
                    "SELECT l.nonce,l.consumed,l.launched,o.nonce FROM study_token_launches AS l "
                    "LEFT JOIN study_token_outcomes AS o ON o.nonce=l.nonce "
                    "WHERE l.run_id=? AND l.turn_reservation_id=?",
                    (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
                ).fetchone()
                return stored == (value.nonce, 1, 0, None)
        except ValueError:
            return False

    def _consume_launch_claim(self, claim: TokenLaunchClaim, *, scheduler_bound: bool) -> None:
        receipt = TokenLaunchClaim.model_validate(claim)
        study, slot, attempt = receipt.receipt.study, receipt.receipt.slot, receipt.receipt.attempt
        with self._transaction() as db:
            row = db.execute(
                "SELECT p.study_id,p.protocol_sha256,p.runtime_sha256,p.model_sha256,p.token_limit,"
                "p.native_manifest_sha256,s.task_id,s.repetition,s.arm,s.token_limit,"
                "a.assignment_id,a.attempt_id,a.prompt_sha256,a.tokens,"
                "l.run_id,l.turn_reservation_id,l.nonce,l.consumed,"
                "EXISTS(SELECT 1 FROM study_token_outcomes o WHERE o.nonce=l.nonce) "
                "FROM study_token_launches l "
                "JOIN study_token_attempts a ON a.run_id=l.run_id "
                "AND a.turn_reservation_id=l.turn_reservation_id "
                "JOIN study_token_slots s ON s.run_id=a.run_id AND s.study_id=a.study_id "
                "JOIN study_token_pins p ON p.study_id=s.study_id "
                "WHERE l.nonce=?",
                (receipt.nonce,),
            ).fetchone()
            expected = (
                study.study_id, study.protocol_sha256, study.runtime_sha256, study.model_sha256, study.token_limit,
                study.native_manifest_sha256, slot.task_id, slot.repetition, slot.arm, slot.token_limit,
                attempt.assignment_id, attempt.attempt_id, attempt.prompt_sha256, attempt.tokens,
                slot.run_id, attempt.turn_reservation_id, receipt.nonce,
            )
            if row is None or row[:17] != expected or row[17] != 0 or row[18] != 0:
                raise ValueError("native launch claim is invalid or already consumed")
            if scheduler_bound:
                self._require_current_scheduler_turn(db, receipt.receipt)
            changed = db.execute(
                "UPDATE study_token_launches SET consumed=1, launched=? WHERE run_id=? AND turn_reservation_id=? "
                "AND nonce=? AND consumed=0",
                (0 if scheduler_bound else 1, slot.run_id, attempt.turn_reservation_id, receipt.nonce),
            )
            if changed.rowcount != 1:
                raise ValueError("native launch claim is invalid or already consumed")

    def _require_current_scheduler_turn(self, db: sqlite3.Connection,
                                        receipt: TokenAdmissionReceipt) -> None:
        slot, attempt = receipt.slot, receipt.attempt
        job = db.execute(
            "SELECT run_id,state,attempt_id,deadline FROM agent_jobs WHERE assignment_id=?",
            (attempt.assignment_id,),
        ).fetchone()
        if job is None or job[:3] != (slot.run_id, "running", attempt.attempt_id):
            raise ValueError("scheduler job is no longer the claimed running attempt")
        self._require_active_run_state(db, slot.run_id)
        reservation = db.execute(
            "SELECT run_id,assignment_id,attempt_id FROM agent_turn_reservations WHERE id=?",
            (attempt.turn_reservation_id,),
        ).fetchone()
        if reservation != (slot.run_id, attempt.assignment_id, attempt.attempt_id):
            raise ValueError("scheduler turn reservation no longer matches the claim")
        session = db.execute(
            "SELECT activated,wall_seconds FROM codex_sessions WHERE run_id=?", (slot.run_id,),
        ).fetchone()
        job_deadline = job[3]
        if (session is None or not isinstance(job_deadline, (int, float))
                or not math.isfinite(job_deadline) or job_deadline <= 0):
            raise ValueError("scheduler launch deadline is unavailable")
        activated, wall_seconds = session
        deadline = job_deadline
        if activated is not None:
            if (not isinstance(activated, (int, float)) or not math.isfinite(activated)
                    or not isinstance(wall_seconds, (int, float)) or not math.isfinite(wall_seconds)
                    or wall_seconds <= 0 or not math.isfinite(activated + wall_seconds)):
                raise ValueError("scheduler run deadline is unavailable")
            deadline = min(deadline, activated + wall_seconds)
        if time.time() >= deadline:
            raise SchedulerLaunchDeadlineExpired("scheduler launch deadline expired before claim consumption")

    def _require_active_run_state(self, db: sqlite3.Connection, run_id: str) -> None:
        from metis.core.contracts import RunStatus
        from metis.core.store import RunStore

        events = RunStore(self.database, read_only=True).read(run_id, connection=db)
        active_statuses = {
            RunStatus.PLANNING, RunStatus.EXECUTING, RunStatus.OBSERVING,
            RunStatus.REPLANNING, RunStatus.VERIFYING,
        }
        if not events or events[-1].status not in active_statuses:
            raise ValueError("scheduler run is missing or not active")

    def reserve(
        self, study: StudyTokenPin, slot: SlotTokenPin, attempt: TokenAttempt,
    ) -> TokenAdmissionReceipt:
        receipt = TokenAdmissionReceipt(study=study, slot=slot, attempt=attempt)
        study, slot, attempt = receipt.study, receipt.slot, receipt.attempt
        if slot.token_limit > study.token_limit:
            raise ValueError("slot token ceiling exceeds study ceiling")
        with self._transaction() as db:
            self._reserve_in_transaction(db, receipt)
        return receipt

    @staticmethod
    def _reserve_in_transaction(db: sqlite3.Connection, receipt: TokenAdmissionReceipt) -> None:
        study, slot, attempt = receipt.study, receipt.slot, receipt.attempt
        if slot.token_limit > study.token_limit:
            raise ValueError("slot token ceiling exceeds study ceiling")
        study_pin = (study.protocol_sha256, study.runtime_sha256,
                     study.model_sha256, study.token_limit, study.native_manifest_sha256)
        slot_pin = (study.study_id, slot.task_id, slot.repetition, slot.arm, slot.token_limit)
        db.execute(
            """INSERT OR IGNORE INTO study_token_pins (
                   study_id, protocol_sha256, runtime_sha256, model_sha256, token_limit, native_manifest_sha256
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (study.study_id, *study_pin),
        )
        recorded_study = db.execute(
            "SELECT protocol_sha256, runtime_sha256, model_sha256, token_limit, native_manifest_sha256 "
            "FROM study_token_pins WHERE study_id = ?", (study.study_id,),
        ).fetchone()
        if recorded_study != study_pin:
            raise ValueError("study token pin mismatch")
        db.execute("INSERT OR IGNORE INTO study_token_slots VALUES (?, ?, ?, ?, ?, ?)",
                   (slot.run_id, *slot_pin))
        recorded_slot = db.execute(
            "SELECT study_id, task_id, repetition, arm, token_limit FROM study_token_slots WHERE run_id = ?",
            (slot.run_id,),
        ).fetchone()
        if recorded_slot != slot_pin:
            raise ValueError("run or study slot token pin mismatch")
        if db.execute(
            "SELECT 1 FROM study_token_attempts WHERE run_id = ? AND turn_reservation_id = ?",
            (slot.run_id, attempt.turn_reservation_id),
        ).fetchone():
            raise ValueError("model turn already has a token receipt")
        study_used = db.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM study_token_attempts WHERE study_id = ?",
            (study.study_id,),
        ).fetchone()[0]
        run_used = db.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM study_token_attempts WHERE run_id = ?",
            (slot.run_id,),
        ).fetchone()[0]
        if study_used + attempt.tokens > study.token_limit:
            raise ValueError("study token budget exhausted")
        if run_used + attempt.tokens > slot.token_limit:
            raise ValueError("run token budget exhausted")
        db.execute(
            "INSERT INTO study_token_attempts (study_id, run_id, turn_reservation_id, "
            "assignment_id, attempt_id, prompt_sha256, tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (study.study_id, slot.run_id, attempt.turn_reservation_id, attempt.assignment_id,
             attempt.attempt_id, attempt.prompt_sha256, attempt.tokens),
        )


    @staticmethod
    def _require_committed_receipt(db: sqlite3.Connection, receipt: TokenAdmissionReceipt) -> None:
        study, slot, attempt = receipt.study, receipt.slot, receipt.attempt
        stored = db.execute(
            """SELECT p.study_id, p.protocol_sha256, p.runtime_sha256, p.model_sha256, p.token_limit,
                      p.native_manifest_sha256, s.task_id, s.repetition, s.arm, s.token_limit,
                      a.assignment_id, a.attempt_id, a.prompt_sha256, a.tokens
               FROM study_token_attempts AS a
               JOIN study_token_slots AS s ON s.run_id = a.run_id AND s.study_id = a.study_id
               JOIN study_token_pins AS p ON p.study_id = s.study_id
               WHERE a.run_id = ? AND a.turn_reservation_id = ?""",
            (slot.run_id, attempt.turn_reservation_id),
        ).fetchone()
        if stored != (
            study.study_id, study.protocol_sha256, study.runtime_sha256, study.model_sha256, study.token_limit,
            study.native_manifest_sha256, slot.task_id, slot.repetition, slot.arm, slot.token_limit,
            attempt.assignment_id, attempt.attempt_id, attempt.prompt_sha256, attempt.tokens,
        ):
            raise ValueError("token receipt does not match committed reservation")

    def _preflight_fixture_receipt(self, receipt: TokenAdmissionReceipt) -> None:
        if receipt.study.native_manifest_sha256 is None:
            raise ValueError("fixture claim requires a committed native manifest")
        try:
            metadata = self.database.lstat()
        except FileNotFoundError:
            raise ValueError("fixture reservation ledger is missing") from None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("fixture reservation ledger must be a singly linked regular file")
        try:
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
                self._require_committed_receipt(db, receipt)
        except sqlite3.OperationalError:
            raise ValueError("fixture reservation ledger unavailable for verification") from None

    @contextmanager
    def _fixture_lock(self, receipt: TokenAdmissionReceipt) -> Iterator[None]:
        # The generic ledger remains usable on platforms without POSIX flock.
        import fcntl

        directory = self.database.with_name(f".{self.database.name}.fixture-locks")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            attributes = os.fstat(directory_fd)
            if attributes.st_uid != os.geteuid() or stat.S_IMODE(attributes.st_mode) != 0o700:
                raise ValueError("fixture claims require a private operator-owned lock directory")
            key = f"{receipt.slot.run_id}:{receipt.attempt.turn_reservation_id}".encode("ascii")
            name = hashlib.sha256(key).hexdigest() + ".lock"
            with _fixture_fd_guard:
                fd = os.open(
                    name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    0o600, dir_fd=directory_fd,
                )
                _fixture_lock_fds.add(fd)
            owner_pid = os.getpid()
            try:
                attributes = os.fstat(fd)
                if (not stat.S_ISREG(attributes.st_mode) or attributes.st_uid != os.geteuid()
                        or stat.S_IMODE(attributes.st_mode) != 0o600 or attributes.st_nlink != 1):
                    raise ValueError("fixture claim lock must be a private operator-owned regular file")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise FixtureClaimBusy("fixture claim already has an active owner") from None
                yield
            finally:
                # A raw fork child has already closed its inherited copy.
                if os.getpid() == owner_pid:
                    with _fixture_fd_guard:
                        _fixture_lock_fds.remove(fd)
                        # Keep the path so later owners lock the same inode.
                        os.close(fd)
        finally:
            os.close(directory_fd)

    def claim_for_launch(self, receipt: TokenAdmissionReceipt) -> TokenLaunchClaim:
        """Return a one-time launch claim only after its transaction commits."""
        return self._claim_for_launch(receipt, fixture_owned=False)

    @contextmanager
    def claim_fixture_launch(self, receipt: TokenAdmissionReceipt) -> Iterator[TokenLaunchClaim]:
        """Hold exclusive fixture ownership until terminal recording or controller exit."""
        receipt = TokenAdmissionReceipt.model_validate(receipt)
        self._preflight_fixture_receipt(receipt)
        with self._fixture_lock(receipt):
            yield self._claim_for_launch(receipt, fixture_owned=True)

    def _claim_for_launch(self, receipt: TokenAdmissionReceipt, *, fixture_owned: bool) -> TokenLaunchClaim:
        claim = TokenLaunchClaim(receipt=receipt, nonce=secrets.token_hex(16))
        receipt = claim.receipt
        with self._transaction() as db:
            self._require_committed_receipt(db, receipt)
            inserted = db.execute(
                """INSERT INTO study_token_launches (run_id, turn_reservation_id, nonce)
                   VALUES (?, ?, ?) ON CONFLICT DO NOTHING""",
                (receipt.slot.run_id, receipt.attempt.turn_reservation_id, claim.nonce),
            )
            if inserted.rowcount != 1:
                raise ValueError("token launch already claimed or nonce unavailable")
            if fixture_owned:
                db.execute("INSERT INTO study_token_fixture_claims (nonce) VALUES (?)", (claim.nonce,))
        return claim

    def reconcile_lost_fixture_claim(self, receipt: TokenAdmissionReceipt) -> TokenLaunchOutcome:
        """Record a lost controller outcome without implying the worker stopped."""
        receipt = TokenAdmissionReceipt.model_validate(receipt)
        self._preflight_fixture_receipt(receipt)
        with self._fixture_lock(receipt):
            with self._transaction() as db:
                self._require_committed_receipt(db, receipt)
                row = db.execute(
                    """SELECT l.nonce FROM study_token_launches AS l
                       JOIN study_token_fixture_claims AS f ON l.nonce = f.nonce
                       WHERE l.run_id = ? AND l.turn_reservation_id = ?""",
                    (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
                ).fetchone()
                if row is None:
                    raise ValueError("reservation has no recoverable fixture claim")
                claim = TokenLaunchClaim(receipt=receipt, nonce=row[0])
            outcome = TokenLaunchOutcome(
                status="lost", native_manifest_sha256=receipt.study.native_manifest_sha256,
            )
            self._record_outcome(claim, outcome, allow_unconsumed_fixture_claim=True)
            return outcome

    def record_outcome(self, claim: TokenLaunchClaim, outcome: TokenLaunchOutcome) -> None:
        """Record one terminal observation without changing the admission charge."""
        self._record_outcome(claim, outcome, allow_unconsumed_fixture_claim=False)

    def _record_outcome(self, claim: TokenLaunchClaim, outcome: TokenLaunchOutcome, *,
                        allow_unconsumed_fixture_claim: bool) -> None:
        claim = TokenLaunchClaim.model_validate(claim)
        outcome = TokenLaunchOutcome.model_validate(outcome)
        receipt = claim.receipt
        if outcome.native_manifest_sha256 != receipt.study.native_manifest_sha256:
            raise ValueError("outcome does not match committed native manifest")
        if outcome.observed_work is not None and outcome.observed_work > receipt.attempt.tokens:
            raise ValueError("observed work exceeds admitted token allowance")
        with self._transaction() as db:
            self._require_committed_receipt(db, receipt)
            stored = db.execute(
                "SELECT nonce,consumed,launched FROM study_token_launches WHERE run_id = ? AND turn_reservation_id = ?",
                (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
            ).fetchone()
            if stored is None or stored[0] != claim.nonce:
                raise ValueError("token launch claim does not match committed nonce")
            if stored[1] != 1:
                fixture_claim = db.execute(
                    "SELECT 1 FROM study_token_fixture_claims WHERE nonce=?", (claim.nonce,),
                ).fetchone() is not None
                if (allow_unconsumed_fixture_claim and stored[1] == 0 and fixture_claim):
                    # Lost fixture claims may be terminalized before consume.
                    pass
                else:
                    raise ValueError("token launch claim has not been consumed")
            elif stored[2] != 1:
                raise ValueError("token launch claim has not started")

            inserted = db.execute(
                """INSERT INTO study_token_outcomes (nonce, status, exit_status, observed_work, native_manifest_sha256)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (claim.nonce, outcome.status, outcome.exit_status, outcome.observed_work, outcome.native_manifest_sha256),
            )
            if inserted.rowcount != 1:
                raise ValueError("token launch outcome already recorded")
