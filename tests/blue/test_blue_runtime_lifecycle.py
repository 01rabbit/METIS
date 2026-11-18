"""METIS Blue runtime: connection states move forward only and cannot outlive their task."""
import threading

import pytest

from metis.blue.runtime.store import Store


@pytest.fixture
def running(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    run, token = store.new_run("lifecycle")
    store.configure(run, token, {"vm": 1})
    store.add_tasks(run, token, [{"id": "a", "prompt": "read", "skill": "soc-triage", "resources": {"vm": 1}}])
    assert store.claim(run, token, "worker")["id"] == "a"
    return store, run, token


def test_stale_running_after_stop_and_finish_is_rejected(running):
    store, run, token = running
    cid = store.begin_connection(run, "a", "vm", "ssh", "identity", False, None)
    store.connection_state(cid, "running", 101)
    with pytest.raises(ValueError, match="running from running"):
        store.connection_state(cid, "running")
    store.connection_state(cid, "stopped")
    store.connection_state(cid, "stopped")                       # repeated stop is harmless
    store.finish(run, token, "a", "done")
    with pytest.raises(ValueError, match="running from stopped"):
        store.connection_state(cid, "running")                   # late callback cannot revive it
    states = [row["state"] for row in store.report(run)["connections"]]
    assert states == ["stopped"]
    with pytest.raises(ValueError, match="Unknown"):
        store.connection_state("missing", "stopped")


def test_running_report_needs_running_task_and_lease(running):
    store, run, _token = running
    cid = store.begin_connection(run, "a", "vm", "ssh", "identity", False, None)
    with store.transaction() as db:                              # simulate a lost lease
        db.execute("DELETE FROM leases WHERE run=? AND task=?", (run, "a"))
    with pytest.raises(ValueError, match="running task and its lease"):
        store.connection_state(cid, "running")


def test_concurrent_finish_and_running_report_are_serialized(running):
    store, run, token = running
    cid = store.begin_connection(run, "a", "vm", "ssh", "identity", False, None)
    store.connection_state(cid, "stopped")
    finisher = Store(store.path)
    reached, release = threading.Event(), threading.Event()

    def hook(point):
        if point == "finish_locked":
            reached.set()
            assert release.wait(10)

    finisher._hook = hook
    thread = threading.Thread(target=finisher.finish, args=(run, token, "a", "done"))
    thread.start()
    assert reached.wait(10)                                      # finish holds BEGIN IMMEDIATE
    outcome = {}

    def report():
        try:
            store.connection_state(cid, "running")
            outcome["error"] = None
        except ValueError as exc:
            outcome["error"] = exc

    reporter = threading.Thread(target=report)
    reporter.start()
    reporter.join(0.5)
    assert reporter.is_alive()                                   # the stale report waits for the lock
    release.set()
    thread.join(10)
    reporter.join(10)
    assert isinstance(outcome["error"], ValueError)
    assert [row["state"] for row in store.report(run)["connections"]] == ["stopped"]
    assert [task["state"] for task in store.tasks(run)] == ["done"]
