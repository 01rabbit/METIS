"""Transactional lifecycle evidence; SQLite is authoritative, JSONL is an export."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

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
_MAX_RUN_AUDIT_LIST_EVENTS = 20_000
_MAX_RUN_AUDIT_LIST_BYTES = 8 * 1024 * 1024
_MAX_RUN_AUDIT_LIST_DISCOVERY_EVENTS = 4_096
_MAX_RUN_AUDIT_LIST_DISCOVERY_BYTES = 5 * 1024 * 1024
_MAX_EVENT_FIELD_BYTES = 256 * 1024
_MAX_RUN_INDEX_FIELD_BYTES = 512
_MAX_SQLITE_INDEX_VALUE_BYTES = 4 * 1024
_RUN_AUDIT_LATEST_INDEX = "events_latest_by_timestamp"


def ensure_run_audit_list_index(path: Path) -> None:
    """Install the bounded run-discovery index once before serving the UI."""
    try:
        with sqlite3.connect(path, timeout=10) as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_EVENT_FIELD_BYTES)
            db.execute(
                f"CREATE INDEX IF NOT EXISTS {_RUN_AUDIT_LATEST_INDEX} "
                "ON events(timestamp DESC, run_id DESC)"
            )
    except sqlite3.Error as exc:
        raise ValueError("operator run list index unavailable") from exc


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


MAX_AUDIT_MANIFEST_BYTES = 1_048_576
MAX_AUDIT_ARTIFACTS = 4096
MAX_AUDIT_MANIFEST_DEPTH = 64


class _AuditManifest(BaseModel):
    """Only registration paths enter this projection; other fields stay private."""

    model_config = ConfigDict(strict=True)
    artifacts: list[str] = Field(max_length=MAX_AUDIT_ARTIFACTS)


def _unique_manifest_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("artifact inventory unavailable or corrupt")
        result[key] = value
    return result


def _invalid_manifest_constant(value: str) -> object:
    raise ValueError("artifact inventory unavailable or corrupt")


def _check_manifest_depth(raw: str) -> None:
    """Bound container nesting before JSON decoding, respecting quoted strings."""
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_AUDIT_MANIFEST_DEPTH:
                raise ValueError("artifact inventory unavailable or corrupt")
        elif char in "]}":
            depth -= 1


def _artifact_inventory(db: sqlite3.Connection, run_id: str) -> dict[str, object]:
    """Count recognized registrations without changing the read snapshot."""
    try:
        columns = {row[1] for row in db.execute("PRAGMA table_info(codex_sessions)")}
        if "manifest" not in columns:
            return {"available": False}
        # Bound stored bytes before transfer to Python, including embedded NULs.
        # The second check below also bounds UTF-8 when a legacy DB uses UTF-16.
        rows = db.execute(
            "SELECT CASE WHEN typeof(manifest)='text' "
            "AND length(CAST(manifest AS BLOB)) <= ? THEN manifest END "
            "FROM codex_sessions WHERE run_id=? LIMIT 2", (MAX_AUDIT_MANIFEST_BYTES, run_id),
        ).fetchall()
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            raise ValueError("invalid manifest")
        if len(rows[0][0].encode("utf-8")) > MAX_AUDIT_MANIFEST_BYTES:
            raise ValueError("oversized manifest")
        _check_manifest_depth(rows[0][0])
        value = json.loads(rows[0][0], object_pairs_hook=_unique_manifest_fields,
                           parse_constant=_invalid_manifest_constant)
        manifest = _AuditManifest.model_validate(value)
        seen: set[str] = set()
        derived = added = 0
        for path in manifest.artifacts:
            parts = path.split("/")
            if (path in seen or any(part in {"", ".", ".."} for part in parts)
                    or "\x00" in path or "\\" in path or PureWindowsPath(path).drive
                    or any(0xD800 <= ord(char) <= 0xDFFF for char in path)):
                raise ValueError("invalid artifact path")
            seen.add(path)
            if parts[0] == ".metis-derived":
                if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{1,8}", parts[1]):
                    raise ValueError("invalid derived path")
                derived += 1
            elif parts[0] == ".metis-added":
                if len(parts) != 2:
                    raise ValueError("invalid added path")
                added += 1
    except sqlite3.Error:
        # SQLite may roll back a transaction on IOERR/NOMEM. Continuing then
        # could combine the validated chain with counters from a newer snapshot.
        if not db.in_transaction:
            raise
        return {"available": False}
    except (ValueError, TypeError, RecursionError):
        return {"available": False}
    return {"available": True, "registered_artifacts": len(seen),
            "registered_derived": derived, "registered_added": added,
            "registered_other": len(seen) - derived - added, "filesystem_verified": False}


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
            db.execute(
                f"CREATE INDEX IF NOT EXISTS {_RUN_AUDIT_LATEST_INDEX} "
                "ON events(timestamp DESC, run_id DESC)"
            )
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

    @contextmanager
    def _snapshot(self, connection: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
            return
        with self._connect() as db:
            db.execute("BEGIN")
            yield db

    @staticmethod
    def _digest(payload: str, timestamp: str, previous: str) -> str:
        return hashlib.sha256(json.dumps(
            [previous, timestamp, payload], separators=(",", ":")
        ).encode()).hexdigest()

    def append(self, event: RunEvent) -> None:
        payload = event.model_dump_json()
        if len(event.run_id.encode("utf-8")) > _MAX_RUN_INDEX_FIELD_BYTES:
            raise ValueError("run identifier exceeds its storage bound")
        if len(payload.encode("utf-8")) > _MAX_EVENT_FIELD_BYTES:
            raise ValueError("event payload exceeds its storage bound")
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
            if type(sequence) is not int or any(
                not isinstance(field, str) for field in (payload, timestamp, previous, digest)
            ):
                raise ValueError("event chain contains invalid storage fields")
            if (sequence != expected or previous != parent
                    or digest != self._digest(payload, timestamp, parent)):
                raise ValueError("event chain is corrupt")
            event = RunEvent.model_validate_json(payload)
            if event.run_id != run_id or event.sequence != sequence:
                raise ValueError("event identity is corrupt")
            events.append(event)
            parent = digest
        return events

    def read(self, run_id: str, *, connection: sqlite3.Connection | None = None) -> list[RunEvent]:
        if connection is not None:
            return self._read(connection, run_id)
        with self._connect() as db:
            return self._read(db, run_id)

    def export_jsonl(self, run_id: str) -> str:
        """Return a consistent validated export; caller chooses output destination."""
        return "".join(event.model_dump_json() + "\n" for event in self.read(run_id))

    def audit_summary(self, run_id: str, *,
                      connection: sqlite3.Connection | None = None) -> dict[str, object] | None:
        """Return a safe lifecycle projection after validating the complete event chain.

        This deliberately omits event details, which may contain free-form text.
        Read-only callers use a single SQLite snapshot and never create a schema.
        Mutable operational counters are explicitly separate from the event chain.
        """
        with self._snapshot(connection) as db:
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
                "model_usage": {"available": False},
                "artifact_inventory": {"available": False},
            }
            if "codex_sessions" in tables:
                operational["artifact_inventory"] = _artifact_inventory(db, run_id)
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
                columns = {row[1] for row in db.execute("PRAGMA table_info(agent_jobs)")}
                if "usage" in columns:
                    known_input = known_output = unknown_jobs = 0
                    jobs = db.execute("SELECT usage FROM agent_jobs WHERE run_id=?", (run_id,)).fetchall()
                    for (raw,) in jobs:
                        try:
                            usage = json.loads(raw) if raw is not None else None
                        except (TypeError, json.JSONDecodeError):
                            usage = None
                        if (not isinstance(usage, dict)
                                or any(type(usage.get(key)) is not int or usage[key] < 0
                                       for key in ("input_tokens", "output_tokens"))):
                            unknown_jobs += 1
                            continue
                        known_input += usage["input_tokens"]
                        known_output += usage["output_tokens"]
                    operational["model_usage"] = {
                        "available": True, "jobs": len(jobs), "unknown_jobs": unknown_jobs,
                        "known_input_tokens": known_input, "known_output_tokens": known_output,
                        "total_tokens": known_input + known_output if unknown_jobs == 0 else None,
                        "cost_usd": None,
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

    def _read_bounded_audit_chain(self, db: sqlite3.Connection, run_id: str, *,
                                  max_events: int, max_bytes: int
                                  ) -> tuple[RunEvent, int, int, dict[str, int]]:
        """Validate one chain incrementally without materializing an unbounded run."""
        cursor = db.execute(
            "SELECT sequence,payload,timestamp,previous_hash,digest FROM events "
            "WHERE run_id=? ORDER BY sequence LIMIT ?", (run_id, max_events + 1),
        )
        parent = ""
        event_count = 0
        byte_count = 0
        counts = {status.value: 0 for status in RunStatus}
        last_event: RunEvent | None = None
        try:
            for sequence, payload, timestamp, previous, digest in cursor:
                event_count += 1
                if event_count > max_events:
                    raise ValueError("run audit list exceeds its event bounds")
                if (type(sequence) is not int or not all(
                        isinstance(value, str) for value in (payload, timestamp, previous, digest))):
                    raise ValueError("run audit event contains invalid storage fields")
                byte_count += sum(len(value.encode("utf-8"))
                                  for value in (run_id, payload, timestamp, previous, digest))
                if byte_count > max_bytes:
                    raise ValueError("run audit list exceeds its event bounds")
                if sequence != event_count - 1:
                    raise ValueError("event chain sequence is corrupt")
                if (previous != parent or digest != self._digest(payload, timestamp, parent)):
                    raise ValueError("event chain is corrupt")
                event = RunEvent.model_validate_json(payload)
                if event.run_id != run_id or event.sequence != sequence:
                    raise ValueError("event identity is corrupt")
                counts[event.status.value] += 1
                last_event = event
                parent = digest
        finally:
            cursor.close()
        if last_event is None:
            raise ValueError("run audit disappeared from snapshot")
        return last_event, event_count, byte_count, counts

    def list_audit_summaries(self, *, limit: int = 20
                             ) -> tuple[list[dict[str, object]], bool]:
        """List newest runs in one read-only snapshot, validating every chain."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("run audit limit must be between 1 and 100")
        with self._connect() as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_EVENT_FIELD_BYTES)
            db.execute("BEGIN")
            # Scan the timestamp index, not the full event table. The first row
            # seen for a run is its latest event; cap discovery independently of
            # the selected-run chain limits below.
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SQLITE_INDEX_VALUE_BYTES)
            cursor = db.execute(
                "SELECT CASE WHEN typeof(run_id)='text' THEN substr(CAST(run_id AS BLOB), 1, ?) END, "
                "length(CAST(run_id AS BLOB)), "
                "CASE WHEN typeof(timestamp)='text' THEN substr(CAST(timestamp AS BLOB), 1, ?) END, "
                "length(CAST(timestamp AS BLOB)) "
                f"FROM events INDEXED BY {_RUN_AUDIT_LATEST_INDEX} "
                "ORDER BY timestamp DESC, run_id DESC "
                "LIMIT ?", (_MAX_RUN_INDEX_FIELD_BYTES, _MAX_RUN_INDEX_FIELD_BYTES,
                            _MAX_RUN_AUDIT_LIST_DISCOVERY_EVENTS + 1),
            )
            run_ids: list[tuple[str, str]] = []
            seen_run_ids: set[str] = set()
            discovery_bytes = 0
            discovery_truncated = False
            for scanned, (run_id_bytes, run_id_length, timestamp_bytes, timestamp_length) in enumerate(
                    cursor, start=1):
                if scanned > _MAX_RUN_AUDIT_LIST_DISCOVERY_EVENTS:
                    discovery_truncated = True
                    break
                if (not isinstance(run_id_bytes, bytes) or not isinstance(timestamp_bytes, bytes)
                        or type(run_id_length) is not int or type(timestamp_length) is not int):
                    raise ValueError("run audit discovery contains invalid index fields")
                if (run_id_length > _MAX_RUN_INDEX_FIELD_BYTES
                        or timestamp_length > _MAX_RUN_INDEX_FIELD_BYTES):
                    raise ValueError("run audit discovery contains oversized index fields")
                discovery_bytes += run_id_length + timestamp_length
                if discovery_bytes > _MAX_RUN_AUDIT_LIST_DISCOVERY_BYTES:
                    discovery_truncated = True
                    break
                try:
                    run_id = run_id_bytes.decode("utf-8")
                    latest_timestamp = timestamp_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("run audit discovery contains invalid index text") from exc
                if run_id not in seen_run_ids:
                    seen_run_ids.add(run_id)
                    run_ids.append((run_id, latest_timestamp))
                    if len(run_ids) == limit:
                        break
            cursor.close()
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_EVENT_FIELD_BYTES)
            summaries: list[dict[str, object]] = []
            total_events = 0
            total_bytes = 0
            for run_id, latest_timestamp in run_ids:
                event_limit = _MAX_RUN_AUDIT_LIST_EVENTS - total_events
                byte_limit = _MAX_RUN_AUDIT_LIST_BYTES - total_bytes
                last_event, run_events, run_bytes, counts = self._read_bounded_audit_chain(
                    db, run_id, max_events=event_limit, max_bytes=byte_limit,
                )
                total_events += run_events
                total_bytes += run_bytes
                budget = None
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "codex_sessions" in tables:
                    row = db.execute(
                        "SELECT max_actions, wall_seconds FROM codex_sessions WHERE run_id=?",
                        (run_id,),
                    ).fetchone()
                    if row is not None:
                        validated = _AuditBudget(max_actions=row[0], wall_seconds=row[1])
                        charged = counts[RunStatus.EXECUTING.value]
                        budget = {**validated.model_dump(), "actions_charged": charged,
                                  "actions_remaining": max(0, validated.max_actions - charged)}
                summaries.append({"run_id": run_id, "status": last_event.status.value,
                                  "last_timestamp": latest_timestamp,
                                  "chain_valid": True,
                                  "codex_budget": budget})
            return summaries, discovery_truncated
