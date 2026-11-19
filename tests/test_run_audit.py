import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import metis.core.store as store_module
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.runtime import ToolRequest
from metis.core.store import RunStore


def audit(database: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "metis.cli", "audit", run_id, "--database", str(database)],
        check=False, capture_output=True, text=True,
    )


def start(session: CodexSession) -> str:
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "audit-fixture", "title": "private-title-omitted",
        "description": "private-description-omitted",
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "audit-fixture"},
    })
    return str(session.start(manifest, max_actions=2, wall_seconds=60)["run_id"])


def test_audit_budget_counts_failed_and_interrupted_reservations_and_extension(tmp_path):
    database = tmp_path / "runs.sqlite"
    session = CodexSession(database)
    run_id = start(session)
    initial = json.loads(audit(database, run_id).stdout)
    assert initial["codex_budget"] == {
        "max_actions": 2, "wall_seconds": 60, "actions_charged": 0, "actions_remaining": 2,
    }

    assert not session.act(run_id, ToolRequest(tool="hex_decode", data="invalid"))["ok"]
    session.extend(run_id, actions=3)
    # Model an interrupted reservation before its OBSERVING event; no worker is launched.
    session._reserve(run_id, "fixture_interruption", private="private-detail-omitted")
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "executing"
    assert summary["codex_budget"] == {
        "max_actions": 5, "wall_seconds": 60, "actions_charged": 2, "actions_remaining": 3,
    }
    assert "private-" not in result.stdout + result.stderr
    assert audit(database, run_id).stdout == result.stdout
    assert database.read_bytes() == before


@pytest.mark.parametrize("with_session_table", [False, True])
def test_audit_budget_is_unavailable_for_non_codex_run(tmp_path, with_session_table):
    database = tmp_path / "runs.sqlite"
    if with_session_table:
        start(CodexSession(database))
    store = RunStore(database)
    store.append(RunEvent(run_id="plain", sequence=0, status=RunStatus.NEW))
    result = audit(database, "plain")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["codex_budget"] is None


def test_audit_includes_run_scoped_mutable_operational_snapshot_without_private_fields(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.executescript(f"""
            CREATE TABLE agent_jobs (run_id TEXT, state TEXT, host_job_id TEXT, failure TEXT);
            CREATE TABLE agent_action_reservations (run_id TEXT, identity TEXT);
            CREATE TABLE agent_run_turn_budgets (
                run_id TEXT PRIMARY KEY, turn_limit INTEGER, turns_reserved INTEGER);
            CREATE TABLE agent_turn_reservations (run_id TEXT, reservation_secret TEXT);
            CREATE TABLE sandbox_workers (run_id TEXT, engine TEXT, container_name TEXT, started REAL);
            CREATE TABLE agent_candidates (run_id TEXT, state TEXT, digest TEXT, path TEXT);
            INSERT INTO agent_jobs VALUES
                ('{run_id}', 'queued', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'running', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'unknown', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'completed', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'failed', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'cancelled', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'timed_out', 'private-host-job-id', 'private-failure'),
                ('{run_id}', 'future-private-state', 'private-host-job-id', 'private-failure'),
                ('another-run', 'running', 'private-host-job-id', 'private-failure');
            INSERT INTO agent_action_reservations VALUES ('{run_id}', 'private-tool-identity');
            INSERT INTO agent_action_reservations VALUES ('another-run', 'private-tool-identity');
            INSERT INTO agent_run_turn_budgets VALUES ('{run_id}', 5, 2);
            INSERT INTO agent_turn_reservations VALUES ('{run_id}', 'private-reservation');
            INSERT INTO agent_turn_reservations VALUES ('{run_id}', 'private-reservation');
            INSERT INTO agent_turn_reservations VALUES ('another-run', 'private-reservation');
            INSERT INTO codex_active_operations VALUES
                ('{run_id}', 'private-operation', 'private-assignment', 'private-attempt', 0, 1.0);
            INSERT INTO codex_active_operations VALUES
                ('another-run', 'private-operation', 'private-assignment', 'private-attempt', 0, 1.0);
            INSERT INTO sandbox_workers VALUES ('{run_id}', 'private-engine', 'private-container', 1.0);
            INSERT INTO sandbox_workers VALUES ('another-run', 'private-engine', 'private-container', 1.0);
            INSERT INTO agent_candidates VALUES ('{run_id}', 'pending', 'private-digest', 'private-path');
            INSERT INTO agent_candidates VALUES ('{run_id}', 'consumed', 'private-digest', 'private-path');
            INSERT INTO agent_candidates VALUES ('another-run', 'pending', 'private-digest', 'private-path');
        """)

    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["operational_state"] == {
        "agent_job_states": {
            "available": True,
            "counts": {"queued": 1, "running": 1, "unknown": 1, "completed": 1,
                       "failed": 1, "cancelled": 1, "timed_out": 1},
            "other": 1,
        },
        "pending_action_reservations": {"available": True, "count": 1},
        "model_turn_budget": {"available": True, "budget": {
            "limit": 5, "reserved_calls": 2, "remaining": 3,
        }},
        "active_operations": {"available": True, "count": 1},
        "registered_sandbox_workers": {"available": True, "count": 1},
        "pending_candidates": {"available": True, "count": 1},
        "model_usage": {"available": False},
    }
    assert "private-" not in result.stdout + result.stderr
    assert audit(database, run_id).stdout == result.stdout
    assert database.read_bytes() == before


def test_audit_operational_tables_are_unavailable_not_fabricated_as_empty(tmp_path):
    database = tmp_path / "runs.sqlite"
    store = RunStore(database)
    store.append(RunEvent(run_id="plain", sequence=0, status=RunStatus.NEW))
    result = audit(database, "plain")
    assert result.returncode == 0, result.stderr
    operational = json.loads(result.stdout)["operational_state"]
    assert all(value == {"available": False} for value in operational.values())


def test_audit_model_usage_reports_only_complete_totals(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT, usage TEXT)")
        db.executemany("INSERT INTO agent_jobs VALUES (?,?,?)", [
            (run_id, "completed", json.dumps({"input_tokens": 8, "output_tokens": 3,
                                 "private": "private-answer-omitted"})),
            (run_id, "running", None),
            ("other-run", "completed", json.dumps({"input_tokens": 999, "output_tokens": 999})),
        ])
    result = audit(database, run_id)
    assert result.returncode == 0, result.stderr
    usage = json.loads(result.stdout)["operational_state"]["model_usage"]
    assert usage == {"available": True, "jobs": 2, "unknown_jobs": 1,
                     "known_input_tokens": 8, "known_output_tokens": 3,
                     "total_tokens": None, "cost_usd": None}
    assert "private-answer" not in result.stdout
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET usage=? WHERE run_id=? AND usage IS NULL",
                   (json.dumps({"input_tokens": 2, "output_tokens": 1}), run_id))
    usage = json.loads(audit(database, run_id).stdout)["operational_state"]["model_usage"]
    assert usage["total_tokens"] == 14 and usage["unknown_jobs"] == 0


def test_audit_fails_closed_on_inconsistent_turn_reservation_counters(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_run_turn_budgets "
                   "(run_id TEXT PRIMARY KEY, turn_limit INTEGER, turns_reserved INTEGER)")
        db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT)")
        db.execute("INSERT INTO agent_run_turn_budgets VALUES (?, ?, ?)", (run_id, 5, 1))
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unavailable or corrupt" in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before


def test_audit_fails_closed_when_turn_reservations_exist_without_budget(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_run_turn_budgets "
                   "(run_id TEXT PRIMARY KEY, turn_limit INTEGER, turns_reserved INTEGER)")
        db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT, reservation_secret TEXT)")
        db.execute("INSERT INTO agent_turn_reservations VALUES (?, ?)", (run_id, "private-reservation"))
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unavailable or corrupt" in result.stderr
    assert "private-reservation" not in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before


@pytest.mark.parametrize("present_table", ["agent_run_turn_budgets", "agent_turn_reservations"])
def test_audit_fails_closed_on_partial_turn_reservation_schema(tmp_path, present_table):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        if present_table == "agent_run_turn_budgets":
            db.execute("CREATE TABLE agent_run_turn_budgets (run_id TEXT, turn_limit INTEGER, turns_reserved INTEGER)")
        else:
            db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT, private_reservation TEXT)")
            db.execute("INSERT INTO agent_turn_reservations VALUES (?, ?)", (run_id, "private-reservation"))
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unavailable or corrupt" in result.stderr
    assert "private-reservation" not in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before


def test_audit_operational_counts_share_the_event_chain_snapshot(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT)")
        db.execute("INSERT INTO agent_jobs VALUES (?, 'queued')", (run_id,))

    store = RunStore(database, read_only=True)
    read_chain = store._read
    written = False

    def read_then_write(db, selected_run):
        nonlocal written
        events = read_chain(db, selected_run)
        if selected_run == run_id and not written:
            with sqlite3.connect(database) as writer:
                writer.execute("UPDATE agent_jobs SET state='completed' WHERE run_id=?", (run_id,))
            written = True
        return events

    store._read = read_then_write
    summary = store.audit_summary(run_id)
    assert written is True
    assert summary["operational_state"]["agent_job_states"]["counts"]["queued"] == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT state FROM agent_jobs WHERE run_id=?", (run_id,)).fetchone()[0] == "completed"


@pytest.mark.parametrize("invalid", [0, -1, 1.5, "private-budget-omitted"])
@pytest.mark.parametrize("column", ["max_actions", "wall_seconds"])
def test_audit_budget_rejects_invalid_configuration_without_echo_or_write(tmp_path, invalid, column):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute(f"UPDATE codex_sessions SET {column}=? WHERE run_id=?", (invalid, run_id))
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unavailable or corrupt" in result.stderr
    assert "private-budget-omitted" not in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before


def test_list_audit_summaries_is_bounded_newest_first_redacted_and_read_only(tmp_path):
    database = tmp_path / "runs.sqlite"
    session = CodexSession(database)
    ids = []
    for _ in range(3):
        ids.append(start(session))
        time.sleep(0.002)
    before = database.read_bytes()

    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(limit=2)

    assert truncated is False
    assert [item["run_id"] for item in summaries] == list(reversed(ids[-2:]))
    assert all(item["chain_valid"] is True for item in summaries)
    assert all(item["codex_budget"]["actions_remaining"] == 2 for item in summaries)
    encoded = json.dumps(summaries)
    assert "private-title-omitted" not in encoded
    assert "private-description-omitted" not in encoded
    assert database.read_bytes() == before


@pytest.mark.parametrize("limit", [0, -1, 101, True, False, 1.5])
def test_list_audit_summaries_rejects_invalid_limits(tmp_path, limit):
    database = tmp_path / "runs.sqlite"
    start(CodexSession(database))
    with pytest.raises(ValueError, match="limit"):
        RunStore(database, read_only=True).list_audit_summaries(limit=limit)


def test_list_audit_summaries_fails_closed_if_any_selected_chain_is_corrupt(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET digest='corrupt' WHERE run_id=? AND sequence=0", (run_id,))
    with pytest.raises(ValueError, match="corrupt"):
        RunStore(database, read_only=True).list_audit_summaries(limit=100)


def test_list_audit_summaries_bounds_run_discovery_scan(tmp_path, monkeypatch):
    database = tmp_path / "runs.sqlite"
    start(CodexSession(database))
    with sqlite3.connect(database) as db:
        indexes = {row[1] for row in db.execute("PRAGMA index_list(events)")}
        assert "events_latest_by_timestamp" in indexes
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT run_id FROM events "
            "INDEXED BY events_latest_by_timestamp "
            "ORDER BY timestamp DESC, run_id DESC LIMIT 2"
        ).fetchall()
        assert any("events_latest_by_timestamp" in row[3] for row in plan)

    monkeypatch.setattr(store_module, "_MAX_RUN_AUDIT_LIST_DISCOVERY_EVENTS", 1)
    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(limit=2)
    assert len(summaries) == 1
    assert truncated is True


@pytest.mark.parametrize("invalid_sequence", ["not-an-integer", 1.5])
def test_list_audit_summaries_rejects_non_integer_sequence_storage(tmp_path, invalid_sequence):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET sequence=? WHERE run_id=? AND sequence=0",
                   (invalid_sequence, run_id))
    with pytest.raises(ValueError, match="sequence"):
        RunStore(database, read_only=True).list_audit_summaries(limit=1)


def test_list_audit_summaries_bounds_discovery_bytes(tmp_path, monkeypatch):
    database = tmp_path / "runs.sqlite"
    start(CodexSession(database))
    monkeypatch.setattr(store_module, "_MAX_RUN_AUDIT_LIST_DISCOVERY_BYTES", 1)
    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(limit=2)
    assert summaries == []
    assert truncated is True


def test_list_audit_summaries_rejects_oversized_legacy_field_before_materializing(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET payload=? WHERE run_id=? AND sequence=0",
                   ("x" * (store_module._MAX_EVENT_FIELD_BYTES + 1), run_id))
    with pytest.raises((ValueError, sqlite3.Error)):
        RunStore(database, read_only=True).list_audit_summaries(limit=100)


def test_list_audit_summaries_rejects_oversized_legacy_index_key(tmp_path):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET run_id=? WHERE run_id=?", ("x" * 513, run_id))
    with pytest.raises(ValueError, match="oversized index fields"):
        RunStore(database, read_only=True).list_audit_summaries(limit=100)


def test_event_append_rejects_payload_above_storage_field_limit(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    event = RunEvent(run_id="bounded-run", sequence=0, status=RunStatus.NEW,
                     detail={"oversized": "x" * store_module._MAX_EVENT_FIELD_BYTES})
    with pytest.raises(ValueError, match="storage bound"):
        store.append(event)


@pytest.mark.parametrize(("event_limit", "byte_limit"), [(1, 8 * 1024 * 1024),
                                                           (20_000, 1)])
def test_list_audit_summaries_enforces_aggregate_event_bounds(
    tmp_path, monkeypatch, event_limit, byte_limit,
):
    database = tmp_path / "runs.sqlite"
    start(CodexSession(database))
    monkeypatch.setattr(store_module, "_MAX_RUN_AUDIT_LIST_EVENTS", event_limit)
    monkeypatch.setattr(store_module, "_MAX_RUN_AUDIT_LIST_BYTES", byte_limit)
    with pytest.raises(ValueError, match="event bounds"):
        RunStore(database, read_only=True).list_audit_summaries(limit=100)
