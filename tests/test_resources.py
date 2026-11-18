"""Shared resource leases, scoped permits and dependency checks."""
import threading
import time

import pytest

from metis.core.ctf_contest import ContestBoard
from metis.core.resources import ResourceBroker, ScopedPermits, dependency_report


def test_unconfigured_resources_are_not_limited(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    with broker.lease("a", {"sandbox": 1}) as first, broker.lease("b", {"sandbox": 1}) as second:
        assert first is None and second is None
    assert broker.status()["leases"] == []


def test_whole_set_or_nothing(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1)
    broker.configure("browser", 1)
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
    broker.configure("sandbox", 2)
    broker.try_acquire("a", {"sandbox": 2})
    with pytest.raises(ValueError, match="cannot shrink"):
        broker.configure("sandbox", 1)


def test_acquire_waits_then_fails_and_reap_releases_expired(tmp_path):
    broker = ResourceBroker(tmp_path / "s.sqlite")
    broker.configure("sandbox", 1)
    lease = broker.try_acquire("a", {"sandbox": 1}, ttl=1)
    with pytest.raises(RuntimeError, match="resource busy"):
        broker.acquire("b", {"sandbox": 1}, wait=0.3, poll=0.1)
    assert broker.reap(now=time.time() + 5) == [lease]
    assert broker.try_acquire("b", {"sandbox": 1})


def test_concurrent_holders_never_exceed_capacity(tmp_path):
    database = tmp_path / "s.sqlite"
    ResourceBroker(database).configure("sandbox", 2)
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
    with pytest.raises(ValueError, match="no wildcards"):
        permits.issue("run", "*", "svc", "patch", "deploy fix")
    with pytest.raises(ValueError, match="reason"):
        permits.issue("run", "task", "svc", "patch", " ")
    permit = permits.issue("run", "task", "svc", "patch", "deploy fix", uses=2)["permit_id"]
    with pytest.raises(PermissionError):
        permits.consume(permit, "run", "task", "svc", "restart")  # different action
    permits.consume(permit, "run", "task", "svc", "patch")
    permits.consume(permit, "run", "task", "svc", "patch")
    with pytest.raises(PermissionError):
        permits.consume(permit, "run", "task", "svc", "patch")  # uses exhausted
    short = permits.issue("run", "task", "svc", "patch", "deploy fix", ttl=1)["permit_id"]
    time.sleep(1.1)
    with pytest.raises(PermissionError):
        permits.consume(short, "run", "task", "svc", "patch")
    revoked = permits.issue("run", "task", "svc", "patch", "deploy fix")["permit_id"]
    assert permits.revoke(revoked)
    with pytest.raises(PermissionError):
        permits.consume(revoked, "run", "task", "svc", "patch")
    assert [item["active"] for item in permits.list("run")] == [False, False, False]


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
