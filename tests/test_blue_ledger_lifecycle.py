"""Task finish and connection start are serialized: no connection survives a successful finish."""
import threading

import pytest

from metis.blue.ledger import ConnectionLedger
from metis.core.resources import init_owner_key, read_owner_key


@pytest.fixture
def ledger(tmp_path):
    database = tmp_path / "state.sqlite"
    init_owner_key(database)
    store = ConnectionLedger(database)
    store.broker.configure("vm", 1, owner_key=read_owner_key(database))
    store.lease_task("run", "a", {"vm": 1})
    return store


def _paused(store, point, reached, release):
    def hook(name):
        if name == point:
            reached.set()
            assert release.wait(10)
    store._hook = hook


def test_start_holding_the_lock_makes_a_concurrent_finish_refuse(ledger):
    starter = ConnectionLedger(ledger.database)
    reached, release = threading.Event(), threading.Event()
    _paused(starter, "begin_locked", reached, release)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault(
        "cid", starter.begin_connection("run", "a", "vm", "ssh", "identity", False, None)))
    thread.start()
    assert reached.wait(10)          # the start holds BEGIN IMMEDIATE and has passed its checks
    finish = {}
    finisher = threading.Thread(target=lambda: finish.setdefault("error", _attempt(ledger.finish_task)))
    finisher.start()
    finisher.join(0.5)
    assert finisher.is_alive()       # the finish waits for the start's transaction
    release.set()
    thread.join(10)
    finisher.join(10)
    assert result["cid"] and isinstance(finish["error"], ValueError)
    assert [lease["holder"] for lease in ledger.broker.status()["leases"]] == ["run/a"]


def test_finish_holding_the_lock_makes_a_late_start_fail(ledger):
    finisher = ConnectionLedger(ledger.database)
    reached, release = threading.Event(), threading.Event()
    _paused(finisher, "finish_locked", reached, release)
    done = {}
    thread = threading.Thread(target=lambda: done.setdefault("released", finisher.finish_task("run", "a")))
    thread.start()
    assert reached.wait(10)
    start = {}
    starter = threading.Thread(target=lambda: start.setdefault("error", _attempt(
        ledger.begin_connection, "run", "a", "vm", "ssh", "identity", False, None)))
    starter.start()
    starter.join(0.5)
    assert starter.is_alive()        # the start waits for the finish's transaction
    release.set()
    thread.join(10)
    starter.join(10)
    assert len(done["released"]) == 1 and isinstance(start["error"], PermissionError)
    assert ledger.report("run")["connections"] == [] and ledger.broker.status()["leases"] == []
    with pytest.raises(PermissionError, match="finished"):
        ledger.lease_task("run", "a", {"vm": 1})   # the fence stays; a new task id is needed
    assert ledger.lease_task("run", "b", {"vm": 1})


def _attempt(function, *args):
    try:
        return function(*args) if args else function("run", "a")
    except (ValueError, PermissionError) as exc:
        return exc


def test_connection_states_only_move_forward(ledger):
    cid = ledger.begin_connection("run", "a", "vm", "ssh", "identity", False, None)
    ledger.connection_state(cid, "running", 123)
    with pytest.raises(ValueError, match="running"):
        ledger.connection_state(cid, "running")          # duplicate report
    ledger.connection_state(cid, "stopped")
    ledger.connection_state(cid, "stopped")              # repeated stop is harmless
    with pytest.raises(ValueError, match="running from stopped"):
        ledger.connection_state(cid, "running")          # late report cannot revive it
    assert ledger.finish_task("run", "a")
    with pytest.raises(ValueError):
        ledger.connection_state(cid, "running")
    with pytest.raises(ValueError, match="unknown"):
        ledger.connection_state("missing", "stopped")
    assert [row["state"] for row in ledger.report("run")["connections"]] == ["stopped"]
