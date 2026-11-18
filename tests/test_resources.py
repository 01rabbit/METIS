"""Shared resource leases, scoped permits and dependency checks."""
import os
import subprocess
import sys
import threading
import time

import pytest

from metis.core.ctf_contest import ContestBoard
from metis.core.resources import (
    ResourceBroker,
    ScopedPermits,
    dependency_report,
    init_owner_key,
    read_owner_key,
)


def _owner(database):
    init_owner_key(database)
    return read_owner_key(database)


def test_unconfigured_resources_are_not_limited(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    with broker.lease("a", {"sandbox": 1}) as first, broker.lease("b", {"sandbox": 1}) as second:
        assert first is None and second is None
    assert broker.status()["leases"] == []


def test_whole_set_or_nothing(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1, owner_key=key)
    broker.configure("browser", 1, owner_key=key)
    held = broker.try_acquire("a", {"browser": 1})
    assert held
    # sandbox is free but browser is not, so nothing is leased.
    assert broker.try_acquire("b", {"sandbox": 1, "browser": 1}) is None
    assert {lease["resource"] for lease in broker.status()["leases"]} == {"browser"}
    assert broker.release(held)
    lease = broker.try_acquire("b", {"sandbox": 1, "browser": 1})
    assert lease and {item["resource"]: item["leased"] for item in broker.status()["resources"]} == {
        "browser": 1, "sandbox": 1}


def test_cannot_shrink_below_leased_units(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    broker.configure("sandbox", 2, owner_key=key)
    broker.try_acquire("a", {"sandbox": 2})
    with pytest.raises(ValueError, match="cannot shrink"):
        broker.configure("sandbox", 1, owner_key=key)


def test_acquire_waits_then_fails_and_reap_releases_only_gone_holders(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1, owner_key=key)
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], check=True,
                              capture_output=True, text=True)
    lease = broker.try_acquire("a", {"sandbox": 1}, ttl=1, pid=int(finished.stdout))
    with pytest.raises(RuntimeError, match="resource busy"):
        broker.acquire("b", {"sandbox": 1}, wait=0.3, poll=0.1)
    assert broker.reap(now=time.time() + 5) == {"reaped": [lease], "kept": []}
    assert broker.try_acquire("b", {"sandbox": 1})


def test_expired_lease_of_live_or_unknown_holder_is_never_reaped(tmp_path):
    """A slow holder past its TTL must not lose its slot to a second holder (no over-allocation)."""
    broker = ResourceBroker(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1, owner_key=key)
    live = broker.try_acquire("live", {"sandbox": 1}, ttl=1, pid=os.getpid())
    assert broker.reap(now=time.time() + 5) == {"reaped": [], "kept": [live]}
    assert broker.try_acquire("second", {"sandbox": 1}) is None
    broker.release(live)
    task_lease = broker.try_acquire("run/task", {"sandbox": 1}, ttl=1)  # no process recorded
    assert broker.reap(now=time.time() + 5) == {"reaped": [], "kept": [task_lease]}
    assert broker.try_acquire("second", {"sandbox": 1}) is None
    with pytest.raises(PermissionError):
        broker.force_release(task_lease, owner_key="not-the-key", reason="holder exited")
    assert broker.force_release(task_lease, owner_key=key, reason="holder exited")
    assert broker.try_acquire("second", {"sandbox": 1})


def test_lease_heartbeat_outlives_the_fixed_ttl(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1, owner_key=key)
    with broker.lease("long", {"sandbox": 1}, ttl=3) as lease:
        time.sleep(4.5)
        expires = broker.status()["leases"][0]["expires"]
        assert expires > time.time()  # renewed past the original three seconds
        assert broker.reap()["kept"] == [] and broker.try_acquire("other", {"sandbox": 1}) is None
        assert broker.status()["leases"][0]["holder_alive"] is True
    assert lease and broker.status()["leases"] == []


def test_capacity_changes_require_the_owner_key(tmp_path):
    database = tmp_path / "s.sqlite"
    broker = ResourceBroker(database)
    with pytest.raises(PermissionError, match="no owner key"):
        broker.configure("sandbox", 1, owner_key=None)
    _owner(database)
    with pytest.raises(PermissionError):
        broker.configure("sandbox", 1, owner_key="guess")


def test_concurrent_holders_never_exceed_capacity(tmp_path):
    database = tmp_path / "s.sqlite"
    ResourceBroker(database).configure("sandbox", 2, owner_key=_owner(database))
    peak = []
    active = []
    lock = threading.Lock()

    def worker(index):
        broker = ResourceBroker(database)
        with broker.lease(f"w{index}", {"sandbox": 1}, wait=10):
            with lock:
                active.append(index)
                peak.append(len(active))
            time.sleep(0.05)
            with lock:
                active.remove(index)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max(peak) <= 2 and len(peak) == 6


def test_permits_are_exact_expiring_and_counted(tmp_path):
    permits = ScopedPermits(tmp_path / "s.sqlite")
    key = _owner(tmp_path / "s.sqlite")
    with pytest.raises(ValueError, match="no wildcards"):
        permits.issue("run", "*", "svc", "patch", "deploy fix", owner_key=key)
    with pytest.raises(ValueError, match="reason"):
        permits.issue("run", "task", "svc", "patch", " ", owner_key=key)
    permit = permits.issue("run", "task", "svc", "patch", "deploy fix", uses=2, owner_key=key)["permit_id"]
    with pytest.raises(PermissionError):
        permits.consume(permit, "run", "task", "svc", "restart")  # different action
    permits.consume(permit, "run", "task", "svc", "patch")
    permits.consume(permit, "run", "task", "svc", "patch")
    with pytest.raises(PermissionError):
        permits.consume(permit, "run", "task", "svc", "patch")  # uses exhausted
    short = permits.issue("run", "task", "svc", "patch", "deploy fix", ttl=1, owner_key=key)["permit_id"]
    time.sleep(1.1)
    with pytest.raises(PermissionError):
        permits.consume(short, "run", "task", "svc", "patch")
    revoked = permits.issue("run", "task", "svc", "patch", "deploy fix", owner_key=key)["permit_id"]
    assert permits.revoke(revoked)
    with pytest.raises(PermissionError):
        permits.consume(revoked, "run", "task", "svc", "patch")
    assert [item["active"] for item in permits.list("run")] == [False, False, False]


def test_specialists_without_the_owner_key_cannot_self_issue_permits(tmp_path, monkeypatch):
    database = tmp_path / ".metis-state" / "metis.sqlite"
    permits = ScopedPermits(database)
    with pytest.raises(PermissionError, match="no owner key"):
        permits.issue("run", "task", "svc", "patch", "self-issued", owner_key="anything")
    created = init_owner_key(database)
    key_file = tmp_path / ".metis-state" / "private" / "owner.key"
    assert created == {"owner_key": str(key_file), "created": True}
    assert oct(key_file.stat().st_mode & 0o777) == "0o600"
    assert oct(key_file.parent.stat().st_mode & 0o777) == "0o700"
    assert init_owner_key(database)["created"] is False  # never rotated silently
    # The database keeps only a digest, so database read access does not reveal the key.
    import sqlite3
    with sqlite3.connect(database) as db:
        stored = db.execute("SELECT key_sha256 FROM metis_owner").fetchone()[0]
    assert key_file.read_text().strip() not in stored
    for presented in (None, "", "0" * 64, stored):
        with pytest.raises(PermissionError):
            permits.issue("run", "task", "svc", "patch", "self-issued", owner_key=presented)
    # A process that cannot read the key file (Codex specialists: the home directory is denied)
    # has no key to present.
    monkeypatch.delenv("METIS_OWNER_KEY", raising=False)
    with pytest.raises(PermissionError, match="owner key unavailable"):
        read_owner_key(database, tmp_path / "unreadable" / "owner.key")
    assert permits.list("run") == []


def test_dependency_report_blocks_descendants_of_failures_and_finds_cycles():
    report = dependency_report(
        {"a": [], "b": ["a"], "c": ["b"], "d": ["x"], "e": ["f"], "f": ["e"], "g": []},
        {"a": "failed", "g": "done"})
    assert report["blocked"] == {"b": ["a"], "c": ["a"]}
    assert report["cycles"] == ["e", "f"] and report["unknown"] == ["d->x"]
    assert report["waiting"] == {"d": ["x"]} and report["ready"] == ["a", "g"]


def test_contest_rejects_cycles_and_reports_abandoned_prerequisites(tmp_path):
    board = ContestBoard(tmp_path / "s.sqlite")
    contest = board.create({"name": "Synthetic", "format": "jeopardy", "max_parallel": 2})["contest_id"]
    board.add(contest, [{"challenge_id": "one", "title": "One"},
                        {"challenge_id": "two", "title": "Two", "prerequisites": ["one"]},
                        {"challenge_id": "three", "title": "Three", "prerequisites": ["two"]}])
    with pytest.raises(ValueError, match="cycle"):
        board.add(contest, [{"challenge_id": "four", "title": "Four", "prerequisites": ["five"]},
                            {"challenge_id": "five", "title": "Five", "prerequisites": ["four"]}])
    board.update(contest, "one", {"state": "abandoned"})
    assert board.board(contest)["blocked_by_prerequisites"] == {"three": ["one"], "two": ["one"]}
    assert board.dispatch(contest)["blocked_by_prerequisites"] == {"three": ["one"], "two": ["one"]}
