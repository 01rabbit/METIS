"""Read-only, answer-free evidence snapshot for a single benchmark run.

This intentionally exports only values that the controller ledger can establish.
Task exposure, workflow completion, provider usage and cost require separate
evidence and are never inferred here.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from metis.core.contracts import RunStatus
from metis.core.store import RunStore

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
OFFICIAL = {"official_ctfd", "official_rctf", "official_ksnctf", "official_html"}


def snapshot_run(database: Path, run_id: str) -> dict[str, object]:
    """Return a fixed-field projection after validating one event chain.

    The read transaction keeps event and reservation counts on one SQLite
    snapshot. Unknown counters remain ``None`` rather than becoming zero.
    """
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run identifier")
    if not database.is_file() or database.is_symlink():
        raise ValueError("benchmark database is unavailable")
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute("BEGIN")
        events = RunStore(database, read_only=True)._read(db, run_id)
        if not events:
            raise ValueError("benchmark run has no events")
        if len(events) > 100_000:
            raise ValueError("benchmark run has too many events")
        timestamps = [row[0] for row in db.execute(
            "SELECT timestamp FROM events WHERE run_id=? ORDER BY sequence", (run_id,))]
        start = datetime.fromisoformat(timestamps[0])
        end = datetime.fromisoformat(timestamps[-1])
        elapsed = (end - start).total_seconds()
        if elapsed < 0 or elapsed > 86_400:
            raise ValueError("benchmark elapsed time is out of range")
        terminal = events[-1]
        verification = terminal.detail.get("verification") if terminal.status == RunStatus.SOLVED else None
        oracle = ("official" if verification in OFFICIAL else
                  "protected_fixture" if verification == "local_fixture_oracle" else "none")
        verified = oracle != "none" and terminal.status == RunStatus.SOLVED
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('agent_turn_reservations','agent_actions')")}
        model_calls = (db.execute("SELECT count(*) FROM agent_turn_reservations WHERE run_id=?",
                                  (run_id,)).fetchone()[0]
                       if "agent_turn_reservations" in tables else None)
        mediated_actions = (db.execute("SELECT count(*) FROM agent_actions WHERE run_id=? AND ok=1",
                                       (run_id,)).fetchone()[0]
                            if "agent_actions" in tables else None)
        return {
            "run_id": run_id, "evidence_sequence": terminal.sequence,
            "terminal_status": terminal.status.value,
            "oracle": oracle, "oracle_verified": verified,
            "event_span_seconds": elapsed,
            "executing_events": sum(event.status == RunStatus.EXECUTING for event in events),
            "reserved_model_calls": model_calls, "successful_mediated_actions": mediated_actions,
            "tokens": None, "cost_usd": None,
            "workflow_complete": None, "task_exposure": None,
        }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m metis.evaluation.heldout_export STATE.sqlite RUN_ID", file=sys.stderr)
        return 2
    try:
        result = snapshot_run(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError, sqlite3.Error):
        print("benchmark evidence export rejected", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
