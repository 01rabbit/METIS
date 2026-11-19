import fcntl
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

import pytest

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.evaluation.issue6_build_pilot import _one_assignment
from metis.evaluation.issue6_canary_watchdog import _CANARY_TABLE, quarantine_expired, start_canary
from metis.evaluation.issue6_pilot_admission import (
    DryRunAdmission,
    DryRunApproval,
    DryRunPhase,
    FrozenCase,
    workspace_binding,
)

DIGEST = "a" * 64


def prepare(root):
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    database = root / "ledger.sqlite"
    scheduler = AgentScheduler(database, BridgeHost())
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=2,
                        catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted")
    artifact = root / "synthetic.json"
    artifact.write_text("{}")
    run_id = scheduler.session.intake(
        title="Public build canary", description="Fixed offline public data", paths=[artifact],
        categories=["misc"], max_actions=2, wall_seconds=120,
    )["run_id"]
    wave = scheduler.ledger.create_wave(run_id, mode="delegated", plan_policy=_one_assignment)
    scheduler.enqueue(run_id, wave["wave_id"])
    job, = scheduler.dispatch(run_id)["started"]
    approval = DryRunApproval(
        approval_id="operator-approved-dry-run", mode="dry_run",
        source_sha256=DIGEST, protocol_sha256=DIGEST, runtime_sha256=DIGEST,
        workspace_sha256=workspace_binding(workspace), model="scripted", expires_at=int(time.time() + 60),
        phase_schema_sha256=(DIGEST, DIGEST),
        cases=tuple(FrozenCase(case_id=f"case-{i}", artifact_hmac=f"{i:064x}") for i in range(36)),
    )
    receipt = DryRunPhase(case_id="case-0", phase=1, artifact_hmac="0" * 64,
                          prompt_hmac=DIGEST, schema_sha256=DIGEST)
    admission = DryRunAdmission(scheduler)
    admission.register(approval)
    admission.claim(approval, workspace)
    admission.open_phase("case-0", 1)
    return database, workspace, admission, (run_id, job["assignment_id"], job["attempt_id"], receipt)


def state(database):
    if not database.exists():
        return None
    with closing(sqlite3.connect(database)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='issue6_canaries'").fetchone():
            return None
        return db.execute("SELECT scratch, state, outcome FROM issue6_canaries").fetchone()


def eventually(check, seconds=5):
    cutoff = time.monotonic() + seconds
    while time.monotonic() < cutoff:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    pytest.fail("public canary did not reach the expected state")


def live_marker(workspace):
    for marker in workspace.glob("canary-*/active"):
        try:
            with marker.open("rb") as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return marker
        except FileNotFoundError:
            continue
    return None


@pytest.mark.parametrize(("behavior", "seconds", "outcome"), [
    ("complete", 2.5, "completed"),
    ("wait_for_stop", 0.8, "deadline"),
])
def test_worker_exit_and_deadline_are_reaped_and_scrubbed(tmp_path, behavior, seconds, outcome):
    database, workspace, admission, args = prepare(tmp_path)
    with start_canary(admission, workspace, *args, behavior=behavior, seconds=seconds) as canary:
        if behavior == "wait_for_stop":
            eventually(lambda: live_marker(workspace))
        assert canary.wait() == 0
    assert state(database)[1:] == ("reaped", outcome)
    assert list(workspace.iterdir()) == []


def _controller_to_kill(root, fork_writer):
    _, workspace, admission, args = prepare(root)
    with start_canary(admission, workspace, *args, behavior="wait_for_stop", seconds=4) as canary:
        if fork_writer and os.fork() == 0:
            (root / "fork-ready").touch()
            time.sleep(2.5)
            (root / "fork-done").touch()
            os._exit(0)
        canary.wait()


@pytest.mark.parametrize("fork_writer", [False, True])
def test_controller_death_stops_guardian_even_if_fork_retains_lease(tmp_path, fork_writer):
    command = (
        "import sys, runpy; from pathlib import Path; "
        "runpy.run_path(sys.argv[1])['_controller_to_kill'](Path(sys.argv[2]), sys.argv[3] == 'True')"
    )
    process = subprocess.Popen([sys.executable, "-c", command, __file__, str(tmp_path), str(fork_writer)])
    try:
        workspace = tmp_path / "workspace"
        eventually(lambda: live_marker(workspace))
        if fork_writer:
            eventually(lambda: (tmp_path / "fork-ready").exists())
        process.kill()
        process.wait(timeout=5)
        database = tmp_path / "ledger.sqlite"
        eventually(lambda: (row := state(database)) and row[1:] == ("reaped", "lease_closed"))
        assert list(workspace.iterdir()) == []
        if fork_writer:
            assert not (tmp_path / "fork-done").exists()
            eventually(lambda: (tmp_path / "fork-done").exists())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_guardian_death_stops_worker_but_quarantines_uncertain_scratch(tmp_path):
    database, workspace, admission, args = prepare(tmp_path)
    with start_canary(admission, workspace, *args, behavior="wait_for_stop", seconds=1.5) as canary:
        marker = eventually(lambda: live_marker(workspace))
        os.kill(canary.guardian_pid, signal.SIGKILL)
        assert canary.wait() == -signal.SIGKILL
        eventually(lambda: live_marker(workspace) is None, seconds=0.75)
        assert marker.is_file()
        assert state(database)[1:] == ("pending", None)
        eventually(lambda: quarantine_expired(database) == 1)
    assert quarantine_expired(database) == 0
    assert state(database)[1:] == ("quarantined", "unconfirmed")
    assert marker.is_file()
    with pytest.raises(ValueError, match="phase budget"):
        start_canary(admission, workspace, *args)


def test_spawn_failure_leaves_prelaunch_record_for_quarantine(tmp_path, monkeypatch):
    database, workspace, admission, args = prepare(tmp_path)

    def fail(*_args, **_kwargs):
        assert state(database)[1:] == ("pending", None)
        assert list(workspace.iterdir()) == []
        raise OSError("injected supervisor spawn failure")

    monkeypatch.setattr("metis.evaluation.issue6_canary_watchdog.subprocess.Popen", fail)
    with pytest.raises(OSError, match="spawn failure"):
        start_canary(admission, workspace, *args, seconds=0.25)
    eventually(lambda: quarantine_expired(database) == 1)
    assert state(database)[1:] == ("quarantined", "unconfirmed")


def test_pending_insert_failure_rolls_back_phase_and_prevents_spawn(tmp_path, monkeypatch):
    database, workspace, admission, args = prepare(tmp_path)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(_CANARY_TABLE)
        db.execute("""
            CREATE TRIGGER fail_pending BEFORE INSERT ON issue6_canaries
            BEGIN SELECT RAISE(ABORT, 'injected pending failure'); END
        """)

    def must_not_start(*_args, **_kwargs):
        pytest.fail("controller attempted to spawn without a committed pending record")

    monkeypatch.setattr("metis.evaluation.issue6_canary_watchdog.subprocess.Popen", must_not_start)
    with pytest.raises(sqlite3.IntegrityError, match="injected pending failure"):
        start_canary(admission, workspace, *args)
    assert state(database) is None
    assert list(workspace.iterdir()) == []
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT turns_reserved FROM agent_run_turn_budgets").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM issue6_dry_reservations").fetchone() == (0,)
