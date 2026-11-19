"""Fail closed on altered historical study progress before any new model call."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from metis.core.contracts import RunEvent, RunStatus
from metis.core.store import RunStore
from metis.evaluation.heldout_protocol import Protocol, schedule
from scripts import run_issue8_rev_memory_study as runner


def completed_prefix(tmp_path: Path) -> tuple[Protocol, Path, dict]:
    protocol = Protocol.model_validate_json(runner.PROTOCOL.read_bytes())
    slot = schedule(protocol)[0]
    run_id = "1" * 32
    database = tmp_path / "state.sqlite"
    store = RunStore(database)
    for index, status in enumerate((RunStatus.NEW, RunStatus.VALIDATED,
                                    RunStatus.CLASSIFIED, RunStatus.PLANNING)):
        store.append(RunEvent(run_id=run_id, sequence=index, status=status))
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE heldout_arm_bindings(run_id TEXT, payload TEXT);
            CREATE TABLE codex_sessions(run_id TEXT, evaluation_split TEXT);
            CREATE TABLE agent_jobs(run_id TEXT, state TEXT);
            CREATE TABLE agent_run_turn_budgets(run_id TEXT, turn_limit INTEGER, turns_reserved INTEGER);
            CREATE TABLE agent_turn_reservations(run_id TEXT);
            CREATE TABLE agent_candidates(run_id TEXT);
            CREATE TABLE agent_autopilot_runs(run_id TEXT, stop_reason TEXT, started REAL);
        """)
        db.execute("INSERT INTO heldout_arm_bindings VALUES (?,?)",
                   (run_id, json.dumps({"protocol_sha256": runner.EXPECTED_PROTOCOL})))
        db.execute("INSERT INTO codex_sessions VALUES (?,?)", (run_id, "heldout"))
        db.execute("INSERT INTO agent_jobs VALUES (?,?)", (run_id, "failed"))
        db.execute("INSERT INTO agent_run_turn_budgets VALUES (?,?,?)", (run_id, 6, 1))
        db.execute("INSERT INTO agent_turn_reservations VALUES (?)", (run_id,))
        db.execute("INSERT INTO agent_autopilot_runs VALUES (?,?,?)",
                   (run_id, "failed_attempt_for_daybreak", 1.0))
    row = {**slot, "run_id": run_id, "phase": "finished", "stop": "failed_attempt_for_daybreak",
           "candidate_proposed": False, "local_control_match": None, "model_calls": 1}
    return protocol, database, {"protocol_sha256": runner.EXPECTED_PROTOCOL, "slots": [row]}


def test_completed_prefix_rejects_progress_and_ledger_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol, database, state = completed_prefix(tmp_path)
    monkeypatch.setattr(runner, "reconcile_memory_snapshots", lambda *_: None)
    monkeypatch.setattr(runner, "reconcile_arm_dispatch", lambda *_: None)
    runner.validate_completed_prefix(protocol, database, state)

    changed = json.loads(json.dumps(state))
    changed["slots"][0]["arm"] = "without_memory"
    with pytest.raises(ValueError, match="slot order"):
        runner.validate_completed_prefix(protocol, database, changed)
    changed = json.loads(json.dumps(state))
    changed["slots"][0]["model_calls"] = 0
    with pytest.raises(ValueError, match="model-call count"):
        runner.validate_completed_prefix(protocol, database, changed)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET state='running'")
    with pytest.raises(ValueError, match="unresolved specialist"):
        runner.validate_completed_prefix(protocol, database, state)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET state='failed'")
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET digest='0' WHERE sequence=0")
    with pytest.raises(ValueError, match="event chain"):
        runner.validate_completed_prefix(protocol, database, state)


def test_completed_prefix_rejects_missing_binding(tmp_path: Path) -> None:
    protocol, database, state = completed_prefix(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM heldout_arm_bindings")
    with pytest.raises(ValueError, match="controller bindings"):
        runner.validate_completed_prefix(protocol, database, state)


def test_closed_study_cannot_start_another_model_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol, database, state = completed_prefix(tmp_path)
    progress = tmp_path / "progress.json"
    progress.write_text(json.dumps(state))
    monkeypatch.setattr(runner, "preflight", lambda *_: (protocol, {}))
    monkeypatch.setattr(runner, "reconcile_memory_snapshots", lambda *_: None)
    monkeypatch.setattr(runner, "reconcile_arm_dispatch", lambda *_: None)
    with pytest.raises(RuntimeError, match="study is closed"):
        runner.run(database, tmp_path, tmp_path, progress)
