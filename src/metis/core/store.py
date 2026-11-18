"""Transactional lifecycle evidence; SQLite is authoritative, JSONL is an export."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from metis.core.contracts import RunEvent, RunStatus

TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.NEW: frozenset({RunStatus.VALIDATED}),
    RunStatus.VALIDATED: frozenset({RunStatus.CLASSIFIED}),
    RunStatus.CLASSIFIED: frozenset({RunStatus.PLANNING}),
    RunStatus.PLANNING: frozenset({RunStatus.EXECUTING}),
    RunStatus.EXECUTING: frozenset({RunStatus.OBSERVING}),
    RunStatus.OBSERVING: frozenset({RunStatus.REPLANNING, RunStatus.VERIFYING}),
    RunStatus.REPLANNING: frozenset({RunStatus.PLANNING}),
    RunStatus.VERIFYING: frozenset({RunStatus.SOLVED, RunStatus.REPLANNING}),
    # Only `CodexSession.extend` (an explicit operator budget extension) emits this.
    RunStatus.EXHAUSTED: frozenset({RunStatus.PLANNING}),
}
STOP_STATES = frozenset({RunStatus.EXHAUSTED, RunStatus.POLICY_DENIED,
                         RunStatus.ERROR, RunStatus.CANCELLED})


class _AuditBudget(BaseModel):
    """Only structured, validated configuration may enter the safe projection."""

    model_config = ConfigDict(strict=True)
    max_actions: int = Field(ge=1)
    wall_seconds: int = Field(ge=1)


class _AuditTurnBudget(BaseModel):
    """Controller-side model-turn reservations, not provider-confirmed usage."""

    model_config = ConfigDict(strict=True)
    turn_limit: int = Field(ge=1)
    turns_reserved: int = Field(ge=0)


class _AuditCount(BaseModel):
    model_config = ConfigDict(strict=True)
    count: int = Field(ge=0)


class RunStore:
    """Controller-only store. Never mount this database in a solver sandbox.

    Hash chaining detects accidental corruption, not a malicious database owner.
    Do not submit secrets, candidate flags or raw tool output as event details.
    """

    def __init__(self, path: Path, *, read_only: bool = False):
        self.path = path
        self.read_only = read_only
        if read_only:
            return
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                payload TEXT NOT NULL, timestamp TEXT NOT NULL,
                previous_hash TEXT NOT NULL, digest TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence))""")
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS deny_{operation.lower()}
                    BEFORE {operation} ON events BEGIN
                    SELECT RAISE(ABORT, 'events are append-only'); END""")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _digest(payload: str, timestamp: str, previous: str) -> str:
        return hashlib.sha256(json.dumps(
            [previous, timestamp, payload], separators=(",", ":")
        ).encode()).hexdigest()

    def append(self, event: RunEvent) -> None:
        payload = event.model_dump_json()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._read(db, event.run_id)
            expected = len(previous)
            if event.sequence != expected:
                raise ValueError("event sequence must be contiguous")
            if not previous:
                if event.status != RunStatus.NEW:
                    raise ValueError("run must begin in NEW")
            else:
                current = previous[-1].status
                if current not in TRANSITIONS or (
                    event.status not in TRANSITIONS[current] | STOP_STATES
                ):
                    raise ValueError(f"invalid transition: {current} -> {event.status}")
            last = db.execute(
                "SELECT digest FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (event.run_id,),
            ).fetchone()
            parent = last[0] if last else ""
            timestamp = datetime.now(UTC).isoformat()
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", (
                event.run_id, event.sequence, payload, timestamp, parent,
                self._digest(payload, timestamp, parent),
            ))

    def _read(self, db: sqlite3.Connection, run_id: str) -> list[RunEvent]:
        rows = db.execute(
            "SELECT sequence, payload, timestamp, previous_hash, digest FROM events "
            "WHERE run_id=? ORDER BY sequence", (run_id,),
        ).fetchall()
        events = []
        parent = ""
        for expected, (sequence, payload, timestamp, previous, digest) in enumerate(rows):
            if (sequence != expected or previous != parent
                    or digest != self._digest(payload, timestamp, parent)):
                raise ValueError("event chain is corrupt")
            event = RunEvent.model_validate_json(payload)
            if event.run_id != run_id or event.sequence != sequence:
                raise ValueError("event identity is corrupt")
            events.append(event)
            parent = digest
        return events

    def read(self, run_id: str) -> list[RunEvent]:
        with self._connect() as db:
            return self._read(db, run_id)

    def export_jsonl(self, run_id: str) -> str:
        """Return a consistent validated export; caller chooses output destination."""
        return "".join(event.model_dump_json() + "\n" for event in self.read(run_id))

    def audit_summary(self, run_id: str) -> dict[str, object] | None:
        """Return a safe lifecycle projection after validating the complete event chain.

        This deliberately omits event details, which may contain free-form text.
        Read-only callers use a single SQLite snapshot and never create a schema.
        Mutable operational counters are explicitly separate from the event chain.
        """
        with self._connect() as db:
            db.execute("BEGIN")
            events = self._read(db, run_id)
            if not events:
                return None
            first_sequence, first_timestamp = db.execute(
                "SELECT sequence, timestamp FROM events WHERE run_id=? "
                "ORDER BY sequence ASC LIMIT 1", (run_id,),
            ).fetchone()
            last_sequence, last_timestamp, digest = db.execute(
                "SELECT sequence, timestamp, digest FROM events WHERE run_id=? "
                "ORDER BY sequence DESC LIMIT 1", (run_id,),
            ).fetchone()
            budget = None
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "codex_sessions" in tables:
                row = db.execute("SELECT max_actions, wall_seconds FROM codex_sessions "
                                 "WHERE run_id=?", (run_id,)).fetchone()
                if row is not None:
                    budget = _AuditBudget(max_actions=row[0], wall_seconds=row[1])
            operational: dict[str, object] = {
                "agent_job_states": {"available": False},
                "pending_action_reservations": {"available": False},
                "model_turn_budget": {"available": False},
                "active_operations": {"available": False},
                "registered_sandbox_workers": {"available": False},
                "pending_candidates": {"available": False},
            }
            if "agent_jobs" in tables:
                known_states = ("queued", "running", "unknown", "completed", "failed",
                                "cancelled", "timed_out")
                placeholders = ",".join("?" for _ in known_states)
                counts = {state: 0 for state in known_states}
                for state, count in db.execute(
                    f"SELECT state, COUNT(*) FROM agent_jobs WHERE run_id=? "
                    f"AND state IN ({placeholders}) GROUP BY state", (run_id, *known_states),
                ):
                    counts[state] = _AuditCount(count=count).count
                other = db.execute(
                    f"SELECT COUNT(*) FROM agent_jobs WHERE run_id=? "
                    f"AND (state IS NULL OR state NOT IN ({placeholders}))", (run_id, *known_states),
                ).fetchone()[0]
                operational["agent_job_states"] = {
                    "available": True, "counts": counts, "other": _AuditCount(count=other).count,
                }
            if "agent_action_reservations" in tables:
                count = db.execute("SELECT COUNT(*) FROM agent_action_reservations WHERE run_id=?",
                                   (run_id,)).fetchone()[0]
                operational["pending_action_reservations"] = {
                    "available": True, "count": _AuditCount(count=count).count,
                }
            turn_tables = {"agent_run_turn_budgets", "agent_turn_reservations"}
            if len(turn_tables & tables) == 1:
                raise ValueError("model-turn reservation schema is incomplete")
            if turn_tables <= tables:
                turn_row = db.execute("SELECT turn_limit, turns_reserved FROM agent_run_turn_budgets "
                                      "WHERE run_id=?", (run_id,)).fetchone()
                reservation_count = db.execute(
                    "SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?", (run_id,),
                ).fetchone()[0]
                reservation_count = _AuditCount(count=reservation_count).count
                if turn_row is None:
                    if reservation_count:
                        raise ValueError("model-turn reservations exist without a budget")
                    operational["model_turn_budget"] = {"available": True, "budget": None}
                else:
                    turn_budget = _AuditTurnBudget(turn_limit=turn_row[0], turns_reserved=turn_row[1])
                    if turn_budget.turns_reserved != reservation_count or reservation_count > turn_budget.turn_limit:
                        raise ValueError("model-turn reservation accounting is inconsistent")
                    operational["model_turn_budget"] = {
                        "available": True,
                        "budget": {"limit": turn_budget.turn_limit,
                                   "reserved_calls": reservation_count,
                                   "remaining": turn_budget.turn_limit - reservation_count},
                    }
            if "codex_active_operations" in tables:
                count = db.execute("SELECT COUNT(*) FROM codex_active_operations WHERE run_id=?",
                                   (run_id,)).fetchone()[0]
                operational["active_operations"] = {
                    "available": True, "count": _AuditCount(count=count).count,
                }
            if "sandbox_workers" in tables:
                count = db.execute("SELECT COUNT(*) FROM sandbox_workers WHERE run_id=?",
                                   (run_id,)).fetchone()[0]
                operational["registered_sandbox_workers"] = {
                    "available": True, "count": _AuditCount(count=count).count,
                }
            if "agent_candidates" in tables:
                count = db.execute("SELECT COUNT(*) FROM agent_candidates WHERE run_id=? AND state='pending'",
                                   (run_id,)).fetchone()[0]
                operational["pending_candidates"] = {
                    "available": True, "count": _AuditCount(count=count).count,
                }
        counts = {status.value: 0 for status in RunStatus}
        for event in events:
            counts[event.status.value] += 1
        charged = counts[RunStatus.EXECUTING.value]
        return {
            "run_id": run_id,
            "status": events[-1].status.value,
            "event_count": len(events),
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
            "first_timestamp": first_timestamp,
            "last_timestamp": last_timestamp,
            "status_counts": counts,
            "chain_valid": True,
            "terminal_digest": digest,
            "codex_budget": None if budget is None else {
                **budget.model_dump(),
                "actions_charged": charged,
                "actions_remaining": max(0, budget.max_actions - charged),
            },
            "operational_state": operational,
        }
