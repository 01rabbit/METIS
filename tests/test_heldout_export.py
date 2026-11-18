"""The P7 exporter must not mistake declarations or secret details for evidence."""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from metis.core.contracts import RunEvent, RunStatus
from metis.core.store import RunStore
from metis.evaluation.heldout_export import main, snapshot_run


def _run(database, run_id: str, *, verification: str | None = None) -> None:
    store = RunStore(database)
    statuses = [RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED,
                RunStatus.PLANNING, RunStatus.EXECUTING, RunStatus.OBSERVING]
    statuses += ([RunStatus.VERIFYING, RunStatus.SOLVED] if verification else
                 [RunStatus.REPLANNING, RunStatus.EXHAUSTED])
    for sequence, status in enumerate(statuses):
        detail = {"private_output": "private-output-canary"} if sequence == 5 else {}
        if status == RunStatus.SOLVED:
            detail = {"verification": verification or ""}
        store.append(RunEvent(run_id=run_id, sequence=sequence, status=status, detail=detail))


def test_snapshot_exports_only_chain_backed_fields_and_unknown_resources(tmp_path):
    database = tmp_path / "state.sqlite"
    run_id = "a" * 32
    _run(database, run_id, verification="official_ksnctf")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT NOT NULL)")
        db.execute("INSERT INTO agent_turn_reservations VALUES (?)", (run_id,))
        db.execute("CREATE TABLE agent_actions (run_id TEXT NOT NULL, ok INTEGER NOT NULL)")
        db.executemany("INSERT INTO agent_actions VALUES (?,?)", [(run_id, 1), (run_id, 0)])
    result = snapshot_run(database, run_id)
    assert result["evidence_sequence"] == 7
    assert result["oracle"] == "official" and result["oracle_verified"] is True
    assert result["reserved_model_calls"] == 1
    assert result["successful_mediated_actions"] == 1
    assert result["event_span_seconds"] >= 0
    assert "elapsed_seconds" not in result
    assert result["tokens"] is None and result["cost_usd"] is None
    assert result["workflow_complete"] is None and result["task_exposure"] is None
    assert "private-output-canary" not in json.dumps(result)


def test_snapshot_does_not_infer_a_solve_or_missing_counters(tmp_path):
    database = tmp_path / "state.sqlite"
    run_id = "b" * 32
    _run(database, run_id)
    result = snapshot_run(database, run_id)
    assert result["terminal_status"] == "exhausted"
    assert result["oracle"] == "none" and result["oracle_verified"] is False
    assert result["reserved_model_calls"] is None
    assert result["successful_mediated_actions"] is None


def test_snapshot_rejects_corrupt_chain_and_unknown_run(tmp_path):
    database = tmp_path / "state.sqlite"
    run_id = "c" * 32
    _run(database, run_id)
    with pytest.raises(ValueError, match="no events"):
        snapshot_run(database, "d" * 32)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET payload='{}' WHERE run_id=? AND sequence=1", (run_id,))
    with pytest.raises(ValueError, match="event chain is corrupt"):
        snapshot_run(database, run_id)


def test_cli_rejects_private_or_invalid_input_without_echo(tmp_path, monkeypatch, capsys):
    database = tmp_path / "missing-private.sqlite"
    monkeypatch.setattr(sys, "argv", ["heldout_export", str(database), "private-candidate"])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-candidate" not in captured.err
    assert not database.exists()


def test_snapshot_bounds_event_count_before_materializing_chain(tmp_path, monkeypatch):
    import metis.evaluation.heldout_export as exporter

    database = tmp_path / "state.sqlite"
    run_id = "e" * 32
    _run(database, run_id)
    monkeypatch.setattr(exporter, "MAX_EVENTS", 2)
    monkeypatch.setattr(RunStore, "_read", lambda *args: pytest.fail("oversized chain was read"))
    with pytest.raises(ValueError, match="too many events"):
        exporter.snapshot_run(database, run_id)


def test_cli_sanitizes_mixed_timezone_timestamps(tmp_path, monkeypatch, capsys):
    database = tmp_path / "state.sqlite"
    run_id = "f" * 32
    _run(database, run_id)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        row = db.execute("SELECT payload,previous_hash FROM events WHERE run_id=? AND sequence=7",
                         (run_id,)).fetchone()
        timestamp = "2026-11-18T00:00:00"
        digest = RunStore._digest(row[0], timestamp, row[1])
        db.execute("UPDATE events SET timestamp=?,digest=? WHERE run_id=? AND sequence=7",
                   (timestamp, digest, run_id))
    monkeypatch.setattr(sys, "argv", ["heldout_export", str(database), run_id])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "benchmark evidence export rejected"
