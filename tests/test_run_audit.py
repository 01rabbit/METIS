import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

import metis.core.store as store_module
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.runtime import ToolRequest
from metis.core.store import (
    MAX_AUDIT_ARTIFACTS,
    MAX_AUDIT_MANIFEST_BYTES,
    MAX_AUDIT_MANIFEST_DEPTH,
    RunStore,
)


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
        "artifact_inventory": {"available": True, "registered_artifacts": 0,
                               "registered_derived": 0, "registered_added": 0,
                               "registered_other": 0, "filesystem_verified": False},
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
                writer.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                               (json.dumps({"artifacts": ["new-after-snapshot.txt"]}), run_id))
            written = True
        return events

    store._read = read_then_write
    summary = store.audit_summary(run_id)
    assert written is True
    assert summary["operational_state"]["agent_job_states"]["counts"]["queued"] == 1
    assert summary["operational_state"]["artifact_inventory"]["registered_artifacts"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT state FROM agent_jobs WHERE run_id=?", (run_id,)).fetchone()[0] == "completed"
    assert store.audit_summary(run_id)["operational_state"]["artifact_inventory"]["registered_artifacts"] == 1


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


def test_list_audit_summaries_validates_chains_without_unbounded_read(tmp_path, monkeypatch):
    database = tmp_path / "runs.sqlite"
    start(CodexSession(database))

    def refuse_unbounded_read(*_args, **_kwargs):
        raise AssertionError("list summary must not materialize a full event chain")

    monkeypatch.setattr(RunStore, "_read", refuse_unbounded_read)
    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(limit=1)

    assert len(summaries) == 1
    assert summaries[0]["chain_valid"] is True
    assert truncated is False


def test_list_audit_summary_timestamp_matches_index_after_clock_regression(
        tmp_path, monkeypatch):
    database = tmp_path / "runs.sqlite"
    store = RunStore(database)
    times = iter([
        datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 10, 1, tzinfo=UTC),
        datetime(2026, 11, 20, 10, 2, tzinfo=UTC),
        datetime(2026, 11, 20, 10, 3, tzinfo=UTC),
        datetime(2026, 11, 20, 9, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 9, 30, tzinfo=UTC),
    ])

    class Clock:
        @staticmethod
        def now(_tz):
            return next(times)

    monkeypatch.setattr(store_module, "datetime", Clock)
    first = "a" * 32
    second = "b" * 32
    statuses = (RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED,
                RunStatus.PLANNING, RunStatus.EXECUTING)
    for sequence, status in enumerate(statuses):
        store.append(RunEvent(run_id=first, sequence=sequence, status=status))
    store.append(RunEvent(run_id=second, sequence=0, status=RunStatus.NEW))

    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(limit=2)

    assert truncated is False
    assert [summary["run_id"] for summary in summaries] == [first, second]
    assert summaries[0]["last_timestamp"] == "2026-11-20T10:03:00+00:00"
    assert summaries[0]["last_timestamp"] > summaries[1]["last_timestamp"]


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
def inventory_fixture(tmp_path, raw):
    database = tmp_path / "runs.sqlite"
    store = RunStore(database)
    store.append(RunEvent(run_id="inventory", sequence=0, status=RunStatus.NEW))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE codex_sessions (run_id TEXT PRIMARY KEY, manifest TEXT, "
                   "max_actions INTEGER, wall_seconds INTEGER)")
        db.execute("INSERT INTO codex_sessions VALUES ('inventory', ?, 2, 60)", (raw,))
    return database


def test_inventory_counts_only_registrations_without_artifact_access_or_writes(tmp_path, monkeypatch):
    derived = ".metis-derived/" + "a" * 32 + ".bin"
    paths = ["private-sentinel-original.txt", ".metis-added/private-sentinel-added.txt", derived,
             "nested/private-sentinel-missing.txt"]
    database = inventory_fixture(tmp_path, json.dumps({"artifacts": paths,
                                                      "description": "private-sentinel-description"}))
    artifact_root = tmp_path / "private-sentinel-root"
    artifact_root.mkdir()
    artifact = artifact_root / "private-sentinel-file"
    artifact.write_text("private-sentinel-content")
    # Neither registered paths nor artifact_root are consulted, even if missing,
    # unrelated, or replaced by an inaccessible filesystem entry.
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE codex_sessions ADD COLUMN artifact_root TEXT")
        db.execute("UPDATE codex_sessions SET artifact_root=?", (str(artifact_root),))
        db.execute("INSERT INTO codex_sessions VALUES ('other', ?, 2, 60, ?)",
                   ('private-sentinel-malformed-other-run', "private-sentinel-other-root"))
        schema_before = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
        dump_before = list(db.iterdump())
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    entries_before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    def forbidden(*args, **kwargs):
        raise AssertionError("audit must not open artifacts, initialize a session, or acquire locks")

    original_stat = os.stat
    database_paths = {database, database.resolve()}

    def database_stat_only(path, *args, **kwargs):
        if Path(path) not in database_paths:
            forbidden()
        return original_stat(path, *args, **kwargs)

    from metis.core import run_lock
    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", forbidden)
        guarded.setattr(os, "stat", database_stat_only)
        guarded.setattr(os, "listdir", forbidden)
        guarded.setattr(os, "scandir", forbidden)
        guarded.setattr(Path, "open", forbidden)
        guarded.setattr(CodexSession, "__init__", forbidden)
        guarded.setattr(run_lock, "run_lock", forbidden)
        guarded.setattr(run_lock, "operation_lock", forbidden)
        summary = RunStore(database, read_only=True).audit_summary("inventory")
    inventory = summary["operational_state"]["artifact_inventory"]
    assert inventory == {"available": True, "registered_artifacts": 4,
                         "registered_derived": 1, "registered_added": 1,
                         "registered_other": 2, "filesystem_verified": False}
    assert "private-sentinel" not in json.dumps(summary)
    result = audit(database, "inventory")
    assert result.returncode == 0, result.stderr
    assert "private-sentinel" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["operational_state"]["artifact_inventory"] == inventory
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == entries_before
    assert {path.relative_to(tmp_path): path.read_bytes()
            for path in tmp_path.rglob("*") if path.is_file()} == before
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema_before
        assert list(db.iterdump()) == dump_before


def test_inventory_zero_and_item_limit(tmp_path):
    database = inventory_fixture(tmp_path, '{"artifacts": []}')
    inventory = RunStore(database, read_only=True).audit_summary("inventory")["operational_state"]["artifact_inventory"]
    assert inventory == {"available": True, "registered_artifacts": 0,
                         "registered_derived": 0, "registered_added": 0,
                         "registered_other": 0, "filesystem_verified": False}
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET manifest=?",
                   (json.dumps({"artifacts": [f"{n}.bin" for n in range(MAX_AUDIT_ARTIFACTS)]}),))
    result = audit(database, "inventory")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["operational_state"]["artifact_inventory"]["registered_artifacts"] == MAX_AUDIT_ARTIFACTS


@pytest.mark.parametrize("raw", [
    None, b'{"artifacts": []}', "private-sentinel-not-json", "null", "[]", "{}",
    '{"artifacts": null}', '{"artifacts": "private-sentinel"}',
    '{"artifacts": {"private-sentinel": {}}}',
    '{"artifacts": [false]}', '{"artifacts": [1]}', '{"artifacts": [{}]}',
    '{"artifacts": [], "artifacts": ["private-sentinel"]}',
    '{"artifacts": [], "private-sentinel": {"nested": 1, "nested": 2}}',
    '{"artifacts": [], "private-sentinel": NaN}',
    '{"artifacts": [], "private-sentinel": Infinity}',
    '{"artifacts": ["private-sentinel", "private-sentinel"]}',
    '{"artifacts": []' + ",\"private-sentinel\":" + "[" * 1100 + "0" + "]" * 1100 + "}",
    json.dumps({"artifacts": [f"{n}.bin" for n in range(MAX_AUDIT_ARTIFACTS + 1)]}),
    json.dumps({"artifacts": [], "private-sentinel": "x" * MAX_AUDIT_MANIFEST_BYTES}),
    json.dumps({"artifacts": [], "private-sentinel": "\u3042" * (MAX_AUDIT_MANIFEST_BYTES // 2)}, ensure_ascii=False),
], ids=lambda raw: type(raw).__name__)
def test_inventory_unavailable_for_malformed_or_oversized_manifest(tmp_path, raw):
    database = inventory_fixture(tmp_path, raw)
    before = database.read_bytes()
    assert_inventory_unavailable(database)
    assert database.read_bytes() == before


def assert_inventory_unavailable(database):
    result = audit(database, "inventory")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "private-sentinel" not in result.stdout
    summary = json.loads(result.stdout)
    assert summary["chain_valid"] is True
    assert summary["status"] == "new"
    assert summary["codex_budget"]["actions_remaining"] == 2
    assert summary["operational_state"]["artifact_inventory"] == {"available": False}
    assert RunStore(database, read_only=True).audit_summary("inventory") == summary
    return summary


def test_inventory_sqlite_text_decode_failure_does_not_discard_audit(tmp_path):
    database = inventory_fixture(tmp_path, '{"artifacts": []}')
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET manifest=CAST(X'80' AS TEXT)")
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT)")
        db.execute("INSERT INTO agent_jobs VALUES ('inventory', 'completed')")
    summary = assert_inventory_unavailable(database)
    assert summary["operational_state"]["agent_job_states"]["counts"]["completed"] == 1


@pytest.mark.parametrize("lose_transaction", [False, True])
def test_inventory_sqlite_error_preserves_or_rejects_the_read_snapshot(tmp_path, lose_transaction):
    database = inventory_fixture(tmp_path, '{"artifacts": []}')
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT)")
        db.execute("INSERT INTO agent_jobs VALUES ('inventory', 'completed')")
    store = RunStore(database, read_only=True)
    later_counter_reads = []

    class InventoryFailureConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT CASE WHEN typeof(manifest)"):
                if lose_transaction:
                    self.rollback()
                raise sqlite3.OperationalError("synthetic inventory SQLite failure")
            if sql.startswith("SELECT state, COUNT(*) FROM agent_jobs"):
                later_counter_reads.append(sql)
            return super().execute(sql, parameters)

    @contextmanager
    def failing_connection():
        db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                             factory=InventoryFailureConnection)
        try:
            with db:
                yield db
        finally:
            db.close()

    store._connect = failing_connection
    if lose_transaction:
        with pytest.raises(sqlite3.OperationalError, match="synthetic inventory SQLite failure"):
            store.audit_summary("inventory")
        assert later_counter_reads == []
    else:
        summary = store.audit_summary("inventory")
        assert summary["chain_valid"] is True
        assert summary["codex_budget"]["actions_remaining"] == 2
        assert summary["operational_state"]["artifact_inventory"] == {"available": False}
        assert summary["operational_state"]["agent_job_states"]["counts"]["completed"] == 1
        assert len(later_counter_reads) == 1


@pytest.mark.parametrize("path", [
    "", ".", "..", "/private-sentinel", "../private-sentinel", "dir/../private-sentinel",
    "dir/./private-sentinel", "./private-sentinel", "dir//private-sentinel", "private-sentinel/",
    "private-sentinel\x00", "private-sentinel\ud800", "dir\\private-sentinel", "C:private-sentinel", "C:/private-sentinel",
    ".metis-derived", ".metis-derived/private-sentinel.bin",
    ".metis-derived/" + "a" * 32 + ".bin/private-sentinel",
    ".metis-derived/" + "A" * 32 + ".bin", ".metis-derived/" + "a" * 32 + ".BIN",
    ".metis-added", ".metis-added/nested/private-sentinel",
])
def test_inventory_unavailable_for_unrecognized_paths_without_disclosure(tmp_path, path):
    database = inventory_fixture(tmp_path, json.dumps({"artifacts": [path]}))
    assert_inventory_unavailable(database)


@pytest.mark.parametrize("paths", [
    ["./a.bin"], ["a/./b"], ["dir/"], ["a.bin", "a.bin"],
    [".metis-added/nested/a.bin"], [".metis-derived/x.bin"],
])
def test_existing_valid_manifest_shapes_preserve_other_audit_output(tmp_path, paths):
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "inventory-compatibility", "title": "private-sentinel-title",
        "description": "private-sentinel-description", "artifacts": paths,
        "scope": {"authorized": True, "granted_by": "synthetic-test",
                  "challenge_id": "inventory-compatibility"},
    })
    database = inventory_fixture(tmp_path, manifest.model_dump_json())
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT)")
        db.execute("INSERT INTO agent_jobs VALUES ('inventory', 'completed')")
    before = database.read_bytes()
    summary = assert_inventory_unavailable(database)
    assert summary["operational_state"]["agent_job_states"]["counts"]["completed"] == 1
    assert database.read_bytes() == before


def test_inventory_byte_bound_includes_exact_limit(tmp_path):
    database = tmp_path / "runs.sqlite"
    # A legacy UTF-16 database must not bypass the separate UTF-8 byte bound.
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA encoding='UTF-16'")
        db.execute("CREATE TABLE legacy_encoding_marker (unused INTEGER)")
    database = inventory_fixture(tmp_path, json.dumps({"artifacts": [], "padding": "\u3042" * 400_000},
                                                      ensure_ascii=False))
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT length(CAST(manifest AS BLOB)) FROM codex_sessions").fetchone()[0] < MAX_AUDIT_MANIFEST_BYTES
    assert_inventory_unavailable(database)
    raw = '{"artifacts": [], "padding": ""}'
    raw = raw.replace('"padding": ""', '"padding": "' + "x" * (MAX_AUDIT_MANIFEST_BYTES - len(raw)) + '"')
    assert len(raw.encode()) == MAX_AUDIT_MANIFEST_BYTES
    # Exact ASCII byte boundary on a normal UTF-8 database.
    utf8_dir = tmp_path / "utf8"
    utf8_dir.mkdir()
    database = inventory_fixture(utf8_dir, raw)
    assert audit(database, "inventory").returncode == 0
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET manifest=?", (raw + " ",))
    assert_inventory_unavailable(database)


def test_inventory_depth_bound_respects_quoted_brackets_and_escapes(tmp_path):
    quoted = json.dumps('private-sentinel' + '[]{}\\"' * 100)
    raw = ('{"artifacts": [], "quoted": ' + quoted + ', "nested": '
           + '[' * (MAX_AUDIT_MANIFEST_DEPTH - 1) + '0'
           + ']' * (MAX_AUDIT_MANIFEST_DEPTH - 1) + '}')
    database = inventory_fixture(tmp_path, raw)
    assert audit(database, "inventory").returncode == 0
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET manifest=?", (raw.replace('"nested": ', '"nested": [').removesuffix('}') + ']}',))
    assert_inventory_unavailable(database)


def test_inventory_legacy_schema_and_missing_session_are_unavailable(tmp_path):
    database = inventory_fixture(tmp_path, '{"artifacts": []}')
    store = RunStore(database, read_only=True)
    RunStore(database).append(RunEvent(run_id="no-session", sequence=0, status=RunStatus.NEW))
    assert store.audit_summary("no-session")["operational_state"]["artifact_inventory"] == {"available": False}
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE codex_sessions DROP COLUMN manifest")
    before = database.read_bytes()
    assert store.audit_summary("inventory")["operational_state"]["artifact_inventory"] == {"available": False}
    assert database.read_bytes() == before
    assert store.audit_summary("no-session")["operational_state"]["artifact_inventory"] == {"available": False}
