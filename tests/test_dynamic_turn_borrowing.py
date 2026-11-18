"""Shared specialist-call borrowing preserves first turns and the run cap."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.ctf_orchestration import AgentLedger


def _setup(tmp_path: Path, *, limit: int = 8, per_run_slots: int = 4
           ) -> tuple[AgentScheduler, str, list[dict[str, Any]]]:
    database = tmp_path / ".metis-state" / "metis.sqlite"
    artifacts = []
    for index in range(2):
        path = tmp_path / f"artifact-{index}.txt"
        path.write_text(f"encoded-{index}")
        artifacts.append(path)
    run_id = CodexSession(database).intake(title="Borrowing", description="Two independent parts",
                                           paths=artifacts, categories=["crypto", "forensics"],
                                           max_actions=20)["run_id"]
    scheduler = AgentScheduler(database, FakeHost())
    scheduler.configure(global_slots=4, per_run_slots=per_run_slots, specialist_turn_budget=limit)
    wave = AgentLedger(database).create_wave(run_id)
    scheduler.enqueue(run_id, wave["wave_id"], dynamic_borrowing=True)
    jobs = scheduler.dispatch(run_id)["started"]
    assert len(jobs) >= min(2, per_run_slots)
    return scheduler, run_id, jobs


def test_borrowing_keeps_one_call_for_each_unstarted_peer(tmp_path: Path) -> None:
    scheduler, run_id, jobs = _setup(tmp_path)
    first = jobs[0]
    for _ in range(8 - (len(jobs) - 1)):
        assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"])
    assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"]) is None
    assert scheduler.model_turn_budget(run_id)["reserved"] == 8 - (len(jobs) - 1)
    for job in jobs[1:]:
        assert scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"])
    assert scheduler.model_turn_budget(run_id) == {"limit": 8, "reserved": 8, "remaining": 0}


def test_queued_peer_keeps_first_call_when_slot_is_full(tmp_path: Path) -> None:
    scheduler, run_id, jobs = _setup(tmp_path, per_run_slots=1)
    assert len(jobs) == 1
    first = jobs[0]
    assert len([job for job in scheduler.jobs(run_id) if job["state"] == "queued"]) >= 1
    for _ in range(8 - (len(scheduler.jobs(run_id)) - 1)):
        assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"])
    assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"]) is None
    assert scheduler.model_turn_budget(run_id)["remaining"] == len(scheduler.jobs(run_id)) - 1


def test_concurrent_borrowing_and_retry_never_exceed_cap(tmp_path: Path) -> None:
    scheduler, run_id, jobs = _setup(tmp_path)
    for job in jobs:
        assert scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"])
    results: list[dict[str, int] | None] = []
    rejected: list[str] = []

    def reserve(job: dict[str, Any]) -> None:
        try:
            results.append(AgentScheduler(scheduler.database, scheduler.host).reserve_model_turn(
                run_id, job["assignment_id"], job["attempt_id"]))
        except ValueError as exc:
            rejected.append(str(exc))

    threads = [threading.Thread(target=reserve, args=(jobs[index % len(jobs)],)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(result is not None for result in results) == 8 - len(jobs)
    assert all("not the running attempt" in message for message in rejected)
    assert scheduler.model_turn_budget(run_id)["reserved"] == 8
    with sqlite3.connect(scheduler.database) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                          (run_id,)).fetchone()[0] == 8


def test_cancel_prevents_borrowing_without_refund(tmp_path: Path) -> None:
    scheduler, run_id, jobs = _setup(tmp_path)
    first = jobs[0]
    assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"])
    scheduler.session.cancel(run_id)
    with pytest.raises(ValueError, match="cancelled"):
        scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"])
    assert scheduler.model_turn_budget(run_id)["reserved"] == 1


def test_retry_keeps_previous_reservations(tmp_path: Path) -> None:
    scheduler, run_id, jobs = _setup(tmp_path)
    first = jobs[0]
    for _ in range(8 - (len(jobs) - 1)):
        scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"])
    assert scheduler.reserve_model_turn(run_id, first["assignment_id"], first["attempt_id"]) is None
    scheduler.retry(first["assignment_id"])
    restarted = next(item for item in scheduler.dispatch(run_id)["started"]
                     if item["assignment_id"] == first["assignment_id"])
    assert scheduler.reserve_model_turn(run_id, restarted["assignment_id"], restarted["attempt_id"]) is None
    assert scheduler.model_turn_budget(run_id)["reserved"] == 8 - (len(jobs) - 1)
