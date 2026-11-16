"""Autopilot drives only scheduler-authorized work and leaves decisions to Daybreak."""
import json
import sqlite3
from pathlib import Path

import pytest

from metis.core.agent_autopilot import autopilot
from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession


def setup_run(tmp_path: Path):
    db = tmp_path / "state.sqlite"
    files = []
    for index in range(2):
        path = tmp_path / f"{index}.txt"
        path.write_text("sample")
        files.append(path)
    run = CodexSession(db).intake(title="Synthetic", description="Analyze data", paths=files,
                                  categories=["crypto", "forensics"], max_actions=80)["run_id"]
    return AgentScheduler(db, BridgeHost()), run


def test_drives_batches_and_resumes_completed_wave_without_new_attempts(tmp_path):
    scheduler, run = setup_run(tmp_path)
    seq = CodexSession(scheduler.database).store.read(run)[-1].sequence

    def drive(scheduler, run_id, assignment, attempt, runner):
        label = assignment.split(":")[-1]
        return scheduler.complete(run_id, assignment, attempt, {
            "hypothesis": f"Hypothesis {label} explains the data.",
            "evidence": f"Evidence {label} describes the sample.",
            "falsifier": f"Parser failure falsifies hypothesis {label}.",
            "next_action": f"Analyze a different window number {label}.",
            "event_sequences": [seq], "status": "inconclusive"})

    first = autopilot(scheduler, run, None, max_waves=2, drive=drive)
    assert first["stop"] == "continuation_for_daybreak"
    assert first["waves"][0]["complete"]
    assert first["metrics"]["daybreak_handoffs"] == 1
    assert first["metrics"]["operations"] == {
        "plan_created": 1, "enqueue": 1, "dispatch": 2, "spawn_retry": 0, "synthesize": 1,
        "continuation_created": 0, "specialists_started": 4,
    }
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))
    second = autopilot(scheduler, run, None, max_waves=2, drive=drive)
    assert second["stop"] == "continuation_for_daybreak"
    assert second["metrics"]["operations"]["specialists_started"] == 0
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))
    with sqlite3.connect(scheduler.database) as db:
        rows = db.execute("SELECT stop_reason, daybreak_handoffs, operations, tokens, cost "
                           "FROM agent_autopilot_runs ORDER BY started").fetchall()
    assert len(rows) == 2
    assert all(row[0] == "continuation_for_daybreak" and row[1] == 1 and row[4] == "unknown" for row in rows)
    assert json.loads(rows[0][2])["specialists_started"] == 4
    assert json.loads(rows[0][3])["input_tokens"] == "unknown"


def test_existing_running_attempt_is_not_driven_again(tmp_path):
    scheduler, run = setup_run(tmp_path)
    wave = scheduler.ledger.create_wave(run)
    scheduler.enqueue(run, wave["wave_id"])
    scheduler.dispatch(run)
    result = autopilot(scheduler, run, None, max_waves=1,
                       drive=lambda *args: pytest.fail("must not run an existing attempt"))
    assert result["stop"] == "existing_attempt_needs_reconciliation"
    assert result["metrics"]["daybreak_handoffs"] == 1
    assert result["metrics"]["operations"]["specialists_started"] == 0


def test_bounds_and_failed_attempt_stops_without_retry(tmp_path):
    scheduler, run = setup_run(tmp_path)
    with pytest.raises(ValueError, match="max-waves"):
        autopilot(scheduler, run, None, max_waves=0)

    def fail(scheduler, run_id, assignment, attempt, runner):
        return scheduler.fail(assignment, attempt, "specialist needs Daybreak")

    result = autopilot(scheduler, run, None, max_waves=1, drive=fail)
    assert result["stop"] == "failed_attempt_for_daybreak"
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))


def test_daybreak_continuation_requires_matching_inconclusive_report(tmp_path):
    scheduler, run = setup_run(tmp_path)
    seq = CodexSession(scheduler.database).store.read(run)[-1].sequence

    def drive(scheduler, run_id, assignment, attempt, runner):
        label = assignment.split(":")[-1]
        return scheduler.complete(run_id, assignment, attempt, {
            "hypothesis": f"Hypothesis {label} explains the data.",
            "evidence": f"Evidence {label} describes the sample.",
            "falsifier": f"Parser failure falsifies hypothesis {label}.",
            "next_action": f"Analyze a different window number {label}.",
            "event_sequences": [seq], "status": "inconclusive"})

    first = autopilot(scheduler, run, None, max_waves=2, drive=drive)
    wave = first["waves"][0]
    report = wave["reports"][0]
    selection = {"wave_id": wave["wave_id"], "report_id": report["report_id"],
                 "reason": report["next_action"]}
    invalid = autopilot(scheduler, run, None, max_waves=2, drive=drive,
                        continuations=[{**selection, "reason": "unrelated assumption"}])
    assert invalid["stop"] == "invalid_or_repeated_continuation"
    result = autopilot(scheduler, run, None, max_waves=2, continuations=[selection],
                       drive=lambda s, r, a, t, runner: s.fail(a, t, "requires Daybreak"))
    assert len(result["waves"]) == 2
    assert result["stop"] == "failed_attempt_for_daybreak"
    assert result["waves"][1]["wave_id"] != wave["wave_id"]


def test_candidate_stops_before_next_batch(tmp_path):
    scheduler, run = setup_run(tmp_path)
    scheduler.configure(per_run_slots=1)
    seq = CodexSession(scheduler.database).store.read(run)[-1].sequence

    def candidate(scheduler, run_id, assignment, attempt, runner):
        scheduler.candidate(run_id, assignment, attempt, "private synthetic answer", [seq])
        return scheduler.fail(assignment, attempt, "candidate handed over")

    result = autopilot(scheduler, run, None, max_waves=2, drive=candidate)
    assert result["stop"] == "candidate_for_daybreak"
    assert sum(j["attempt_no"] for j in scheduler.jobs(run)) == 1
    assert "private synthetic answer" not in str(result)
