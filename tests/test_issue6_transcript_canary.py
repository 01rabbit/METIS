import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from test_issue6_canary_watchdog import eventually, prepare, state

from metis.evaluation._issue6_transcript_canary import (
    _ANSWER,
    _THREAD,
    _TRANSCRIPT_TABLE,
    _fresh_last_message,
)
from metis.evaluation.issue6_canary_watchdog import quarantine_expired, start_transcript_canary


def terminal(database):
    with closing(sqlite3.connect(database)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='issue6_canary_transcripts'").fetchone()
        if not exists:
            return None
        row = db.execute("SELECT evidence FROM issue6_canary_transcripts").fetchone()
        return None if row is None else json.loads(row[0])


def assert_charged_once(database):
    with closing(sqlite3.connect(database)) as db:
        turns_reserved, = db.execute("SELECT turns_reserved FROM agent_run_turn_budgets").fetchone()
        assert turns_reserved == 1
        for table in ("agent_turn_reservations", "issue6_dry_reservations", "issue6_canaries"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (1,)


def live_stub(workspace):
    for last in workspace.glob("canary-*/last.json"):
        try:
            with last.open("rb") as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return last
        except FileNotFoundError:
            continue
    return None


@pytest.mark.parametrize(("mode", "outcome"), [
    ("complete", "completed"),
    ("tool", "tool_policy"),
    ("wrong_file", "invalid_response"),
    ("stdout_overflow", "capture_limit"),
    ("stderr_overflow", "capture_limit"),
    ("last_overflow", "capture_limit"),
    ("nonzero", "runtime_failure"),
])
def test_fixed_stub_actual_guardian_finalizes_only_sanitized_evidence(tmp_path, mode, outcome):
    database, workspace, admission, args = prepare(tmp_path)
    with start_transcript_canary(admission, workspace, *args, mode=mode) as canary:
        assert canary.wait() == 0
    assert state(database)[1:] == ("reaped", outcome)
    row = terminal(database)
    assert row["outcome"] == outcome
    if outcome == "completed":
        assert row["cli_usage"]["input_tokens"] == 3
        assert len(row["thread_hmac"]) == len(row["response_hmac"]) == 64
        assert row["thread_hmac"] != row["response_hmac"]
    else:
        assert row["cli_usage"] is row["thread_hmac"] is row["response_hmac"] is None
    assert_charged_once(database)
    assert list(workspace.iterdir()) == []
    assert _THREAD.encode() not in database.read_bytes() and _ANSWER not in database.read_bytes()
    with pytest.raises(ValueError, match="phase budget"):
        start_transcript_canary(admission, workspace, *args, mode=mode)
    assert_charged_once(database)


def test_fresh_file_is_exclusive_empty_and_symlinks_are_refused(tmp_path):
    last = tmp_path / "last.json"
    last.write_bytes(b"stale")
    with pytest.raises(FileExistsError):
        _fresh_last_message(last)
    assert last.read_bytes() == b"stale"
    alias = tmp_path / "alias"
    alias.symlink_to(last)
    with pytest.raises(FileExistsError):
        _fresh_last_message(alias)
    assert last.read_bytes() == b"stale"
    fresh = tmp_path / "fresh"
    descriptor = _fresh_last_message(fresh)
    try:
        assert os.fstat(descriptor).st_size == 0
        assert os.fstat(descriptor).st_mode & 0o777 == 0o600
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(("request_stop", "outcome"), [(False, "deadline"), (True, "cancelled")])
def test_actual_deadline_or_cancellation_reaps_without_refund(tmp_path, request_stop, outcome):
    database, workspace, admission, args = prepare(tmp_path)
    with start_transcript_canary(admission, workspace, *args, mode="hold", seconds=2) as canary:
        eventually(lambda: live_stub(workspace))
        if request_stop:
            canary.cancel()
        assert canary.wait() == 0
    assert terminal(database)["outcome"] == outcome
    assert_charged_once(database)
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("trigger", [
    "BEFORE INSERT ON issue6_canary_transcripts BEGIN SELECT RAISE(ABORT, 'injected terminal failure'); END",
    "AFTER INSERT ON issue6_canary_transcripts BEGIN DELETE FROM issue6_canary_transcripts; END",
])
def test_terminal_receipt_insert_failure_rolls_back_cas_but_not_phase_charge(tmp_path, trigger):
    database, workspace, admission, args = prepare(tmp_path)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(_TRANSCRIPT_TABLE)
        db.execute(f"CREATE TRIGGER fail_receipt {trigger}")
    with start_transcript_canary(admission, workspace, *args, seconds=2) as canary:
        assert canary.wait() != 0
    assert state(database)[1:] == ("pending", None)
    assert terminal(database) is None
    assert list(workspace.iterdir()) == []
    assert_charged_once(database)
    eventually(lambda: quarantine_expired(database) == 1)
    assert state(database)[1:] == ("quarantined", "unconfirmed")


def test_lost_pending_cas_preserves_quarantine_after_actual_child_stop(tmp_path):
    database, workspace, admission, args = prepare(tmp_path)
    with start_transcript_canary(admission, workspace, *args, mode="hold", seconds=3) as canary:
        eventually(lambda: live_stub(workspace))
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE issue6_canaries SET state='quarantined', outcome='unconfirmed'")
        canary.cancel()
        assert canary.wait() != 0
    assert state(database)[1:] == ("quarantined", "unconfirmed")
    assert terminal(database) is None
    assert list(workspace.iterdir()) == []
    assert_charged_once(database)


def test_guardian_death_leaves_no_completion_and_worker_releases_lease(tmp_path):
    database, workspace, admission, args = prepare(tmp_path)
    with start_transcript_canary(admission, workspace, *args, mode="hold", seconds=2) as canary:
        last = eventually(lambda: live_stub(workspace))
        os.kill(canary.guardian_pid, signal.SIGKILL)
        assert canary.wait() == -signal.SIGKILL
        eventually(lambda: live_stub(workspace) is None, seconds=0.75)
    assert last.exists()
    assert terminal(database) is None
    assert state(database)[1:] == ("pending", None)
    assert_charged_once(database)
    eventually(lambda: quarantine_expired(database) == 1)


def _controller(root):
    _database, workspace, admission, args = prepare(root)
    with start_transcript_canary(admission, workspace, *args, mode="hold", seconds=4) as canary:
        canary.wait()


def test_controller_death_is_finalized_as_cancellation_after_reap(tmp_path):
    command = (
        "import sys, runpy; from pathlib import Path; "
        "sys.path.insert(0, str(Path(sys.argv[1]).parent)); "
        "runpy.run_path(sys.argv[1])['_controller'](Path(sys.argv[2]))"
    )
    process = subprocess.Popen([sys.executable, "-c", command, __file__, str(tmp_path)])
    database = tmp_path / "ledger.sqlite"
    workspace = tmp_path / "workspace"
    try:
        eventually(lambda: live_stub(workspace))
        process.kill()
        process.wait(timeout=5)
        eventually(lambda: terminal(database))
        assert terminal(database)["outcome"] == "cancelled"
        assert state(database)[1:] == ("reaped", "cancelled")
        assert list(workspace.iterdir()) == []
        assert_charged_once(database)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_spawn_failure_retains_charge_and_no_terminal_evidence(tmp_path, monkeypatch):
    database, workspace, admission, args = prepare(tmp_path)

    def fail(*_args, **_kwargs):
        assert state(database)[1:] == ("pending", None)
        assert_charged_once(database)
        raise OSError("injected guardian spawn failure")

    monkeypatch.setattr("metis.evaluation.issue6_canary_watchdog.subprocess.Popen", fail)
    with pytest.raises(OSError, match="spawn failure"):
        start_transcript_canary(admission, workspace, *args, seconds=0.25)
    assert terminal(database) is None
    assert list(workspace.iterdir()) == []
    eventually(lambda: quarantine_expired(database) == 1)
    assert_charged_once(database)
