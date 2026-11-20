"""Autopilot drives only scheduler-authorized work and leaves decisions to Daybreak."""
import json
import sqlite3
from pathlib import Path

import pytest

from metis.core.agent_autopilot import autopilot
from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession


class BudgetedTestRunner:
    model_turn_budget_enforced = True


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

    first = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, drive=drive)
    assert first["stop"] == "continuation_for_daybreak"
    assert first["waves"][0]["complete"]
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))
    second = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, drive=drive)
    assert second["stop"] == "continuation_for_daybreak"
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))


def test_existing_running_attempt_is_not_driven_again(tmp_path):
    scheduler, run = setup_run(tmp_path)
    wave = scheduler.ledger.create_wave(run)
    scheduler.enqueue(run, wave["wave_id"])
    scheduler.dispatch(run)
    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1,
                       drive=lambda *args: pytest.fail("must not run an existing attempt"))
    assert result["stop"] == "existing_attempt_needs_reconciliation"


def test_driver_exception_persists_handoff_and_preserves_attempts_for_reconciliation(tmp_path):
    scheduler, run = setup_run(tmp_path)

    def crash(*_args):
        raise RuntimeError("private worker output must not be exposed")

    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=crash)
    assert result["stop"] == "specialist_driver_exception"
    assert result["metrics"]["daybreak_handoffs"] == 1
    assert result["metrics"]["specialist_turns"] == 0
    assert result["metrics"]["specialist_outcomes"] == {"driver_exception": 2}
    assert "private worker output" not in str(result)
    jobs = scheduler.jobs(run)
    assert jobs and any(job["state"] in {"running", "unknown"} for job in jobs)
    assert all(job["state"] in {"running", "unknown", "queued"} for job in jobs)
    with sqlite3.connect(scheduler.database) as db:
        row = db.execute("SELECT stop_reason,daybreak_handoffs FROM agent_autopilot_runs WHERE invocation_id=?",
                         (result["metrics"]["invocation_id"],)).fetchone()
    assert row == ("specialist_driver_exception", 1)

    resumed = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=crash)
    assert resumed["stop"] == "existing_attempt_needs_reconciliation"
    assert resumed["metrics"]["specialist_outcomes"] == {}
    assert [job["assignment_id"] for job in scheduler.jobs(run) if job["state"] in {"running", "unknown"}] \
        == [job["assignment_id"] for job in jobs if job["state"] in {"running", "unknown"}]
    assert all(job["attempt_no"] <= 1 for job in scheduler.jobs(run))


def test_mixed_completed_and_crashed_batch_keeps_spent_turn_and_reconciliation_state(tmp_path):
    scheduler, run = setup_run(tmp_path)

    def mixed_drive(scheduler, run_id, assignment, attempt, runner):
        if assignment.endswith(":1"):
            _complete_synthetic_report(scheduler, run_id, assignment, attempt)
            return {"failure_category": "none", "failure": "private completed specialist output"}
        if assignment.endswith(":2"):
            reservation = scheduler.reserve_model_turn(run_id, assignment, attempt)
            assert reservation == {"turn": 1, "limit": 24, "remaining": 23}
            raise RuntimeError("private interrupted specialist output")
        pytest.fail("first batch should contain only two assignments")

    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=mixed_drive)
    assert result["stop"] == "specialist_driver_exception"
    assert result["metrics"]["daybreak_handoffs"] == 1
    assert result["metrics"]["specialist_turns"] == 1
    assert result["metrics"]["specialist_outcomes"] == {"none": 1, "driver_exception": 1}
    assert "private interrupted specialist output" not in str(result)
    assert "private completed specialist output" not in str(result)
    jobs = scheduler.jobs(run)
    assert sum(job["state"] == "completed" for job in jobs) == 1
    assert sum(job["state"] == "running" for job in jobs) == 1
    assert sum(job["state"] == "queued" for job in jobs) == 2
    assert scheduler.model_turn_budget(run) == {"limit": 24, "reserved": 1, "remaining": 23}
    with sqlite3.connect(scheduler.database) as db:
        reservations = db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?", (run,)).fetchone()[0]
        persisted = db.execute("SELECT stop_reason,daybreak_handoffs,specialist_turns,specialist_outcomes "
                               "FROM agent_autopilot_runs WHERE invocation_id=?",
                               (result["metrics"]["invocation_id"],)).fetchone()
    assert reservations == 1
    assert persisted[:3] == ("specialist_driver_exception", 1, 1)
    assert json.loads(persisted[3]) == {"none": 1, "driver_exception": 1}

    resumed = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=mixed_drive)
    assert resumed["stop"] == "existing_attempt_needs_reconciliation"
    assert scheduler.model_turn_budget(run) == {"limit": 24, "reserved": 1, "remaining": 23}
    assert all(job["attempt_no"] <= 1 for job in scheduler.jobs(run))


def test_bounds_and_failed_attempt_stops_without_retry(tmp_path):
    scheduler, run = setup_run(tmp_path)
    with pytest.raises(ValueError, match="max-waves"):
        autopilot(scheduler, run, BudgetedTestRunner(), max_waves=0)

    def fail(scheduler, run_id, assignment, attempt, runner):
        return scheduler.fail(assignment, attempt, "specialist needs Daybreak")

    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=fail)
    assert result["stop"] == "failed_attempt_for_daybreak"
    assert all(j["attempt_no"] == 1 for j in scheduler.jobs(run))


def test_specialist_outcomes_use_only_fixed_categories_across_batches(tmp_path):
    scheduler, run = setup_run(tmp_path)
    categories = {
        "1": {"failure_category": "provider_failure"},
        "2": {},
        "3": {"failure_category": "private unrecognized category"},
        "4": {"failure_category": ["private malformed category"]},
    }

    def drive(scheduler, run_id, assignment, attempt, runner):
        scheduler.fail(assignment, attempt, "synthetic failure")
        return categories[assignment.rsplit(":", 1)[-1]]

    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=1, drive=drive)
    assert result["stop"] == "failed_attempt_for_daybreak"
    assert result["operations"]["dispatch"] == 2
    assert result["metrics"]["specialist_outcomes"] == {
        "provider_failure": 1, "missing_or_invalid_category": 3,
    }
    assert "private " not in str(result["metrics"])
    with sqlite3.connect(scheduler.database) as db:
        stored = db.execute("SELECT specialist_outcomes FROM agent_autopilot_runs").fetchone()[0]
    assert json.loads(stored) == result["metrics"]["specialist_outcomes"]


def test_specialist_outcome_schema_preserves_legacy_invocation_rows(tmp_path):
    scheduler, run = setup_run(tmp_path)
    with sqlite3.connect(scheduler.database) as db:
        db.execute("""CREATE TABLE agent_autopilot_runs (
            invocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, started REAL NOT NULL, finished REAL NOT NULL,
            elapsed_seconds REAL NOT NULL, max_waves INTEGER NOT NULL, waves_inspected INTEGER NOT NULL,
            stop_reason TEXT NOT NULL, daybreak_handoffs INTEGER NOT NULL, operations TEXT NOT NULL,
            specialist_turns INTEGER NOT NULL, tokens TEXT NOT NULL, cost TEXT NOT NULL)""")
        db.execute("INSERT INTO agent_autopilot_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("legacy", run, 1, 2, 1, 1, 0, "legacy stop", 0, "{}", 0, "{}", "unknown"))

    result = autopilot(scheduler, run, object(), max_waves=1)
    assert result["metrics"]["specialist_outcomes"] == {}
    with sqlite3.connect(scheduler.database) as db:
        rows = db.execute("SELECT invocation_id,stop_reason,specialist_outcomes FROM agent_autopilot_runs")
        assert {invocation: (stop, stored) for invocation, stop, stored in rows} == {
            "legacy": ("legacy stop", None),
            result["metrics"]["invocation_id"]: ("host_model_turn_budget_unenforced", "{}"),
        }


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

    first = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, drive=drive)
    wave = first["waves"][0]
    report = wave["reports"][0]
    selection = {"wave_id": wave["wave_id"], "report_id": report["report_id"],
                 "reason": report["next_action"]}
    invalid = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, drive=drive,
                        continuations=[{**selection, "reason": "unrelated assumption"}])
    assert invalid["stop"] == "invalid_or_repeated_continuation"
    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, continuations=[selection],
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

    result = autopilot(scheduler, run, BudgetedTestRunner(), max_waves=2, drive=candidate)
    assert result["stop"] == "candidate_for_daybreak"
    assert sum(j["attempt_no"] for j in scheduler.jobs(run)) == 1
    assert "private synthetic answer" not in str(result)


def _complete_synthetic_report(scheduler, run_id, assignment, attempt):
    job = next(job for job in scheduler.jobs(run_id) if job["assignment_id"] == assignment)
    sequence = CodexSession(scheduler.database).store.read(run_id)[-1].sequence
    return scheduler.complete(run_id, assignment, attempt, {
        "hypothesis": f"Role {job['role']} supports a parser hypothesis.",
        "evidence": f"Run event {sequence} contains the synthetic observation.",
        "falsifier": f"A failed parser result would falsify role {job['role']}.",
        "next_action": f"Inspect a different input family for {job['role']}.",
        "event_sequences": [sequence], "status": "inconclusive"})


def test_autopilot_matches_manual_one_wave_control_flow_and_persists_metrics(tmp_path):
    manual_root, auto_root = tmp_path / "manual", tmp_path / "auto"
    manual_root.mkdir()
    auto_root.mkdir()
    manual, manual_run = setup_run(manual_root)
    automatic, auto_run = setup_run(auto_root)
    manual.configure(per_run_slots=2)
    automatic.configure(per_run_slots=2)

    plan = manual.ledger.create_wave(manual_run)
    manual_operations = {"plan_created": 1, "enqueue": 1, "dispatch": 0, "spawn_retry": 0,
                         "synthesize": 0, "continuation_created": 0, "specialists_started": 0}
    manual.enqueue(manual_run, plan["wave_id"])
    while any(job["state"] == "queued" for job in manual.jobs(manual_run, plan["wave_id"])):
        manual_operations["dispatch"] += 1
        started = manual.dispatch(manual_run)["started"]
        assert started
        manual_operations["specialists_started"] += len(started)
        for job in started:
            _complete_synthetic_report(manual, manual_run, job["assignment_id"], job["attempt_id"])
    manual_synthesis = manual.ledger.synthesize(manual_run, plan["wave_id"])
    manual_operations["synthesize"] += 1

    def drive(scheduler, run_id, assignment, attempt, runner):
        return _complete_synthetic_report(scheduler, run_id, assignment, attempt)

    auto_result = autopilot(automatic, auto_run, BudgetedTestRunner(), max_waves=1, drive=drive)
    assert auto_result["stop"] == "wave_limit"
    assert auto_result["metrics"]["daybreak_handoffs"] == 1
    expected_operations = {"plan_created": 1, "enqueue": 1, "dispatch": 2, "spawn_retry": 0,
                           "synthesize": 1, "continuation_created": 0, "specialists_started": 4}
    assert manual_operations == expected_operations
    assert auto_result["operations"] == expected_operations
    manual_shape = (manual_synthesis["complete"], len(manual_synthesis["reports"]),
                    sorted(item["status"] for item in manual_synthesis["reports"]))
    auto_synthesis = auto_result["waves"][0]
    auto_shape = (auto_synthesis["complete"], len(auto_synthesis["reports"]),
                  sorted(item["status"] for item in auto_synthesis["reports"]))
    assert auto_shape == manual_shape

    metrics = auto_result["metrics"]
    with sqlite3.connect(automatic.database) as db:
        row = db.execute("SELECT run_id,started,finished,elapsed_seconds,max_waves,waves_inspected,stop_reason,"
                         "daybreak_handoffs,operations,specialist_turns,tokens,cost FROM agent_autopilot_runs "
                         "WHERE invocation_id=?", (metrics["invocation_id"],)).fetchone()
    assert row is not None
    (stored_run, started, finished, elapsed, max_waves, waves_inspected, stop, handoffs,
     operations, specialist_turns, tokens, cost) = row
    assert stored_run == auto_run and started <= finished
    assert abs((finished - started) - elapsed) <= 0.001
    assert elapsed == metrics["elapsed_seconds"]
    assert max_waves == metrics["max_waves"]
    assert waves_inspected == metrics["waves_inspected"]
    assert stop == metrics["stop_reason"] == auto_result["stop"]
    assert handoffs == metrics["daybreak_handoffs"]
    assert json.loads(operations) == metrics["operations"]
    assert specialist_turns == metrics["specialist_turns"]
    assert json.loads(tokens) == metrics["tokens"]
    assert cost == metrics["cost"]


def test_zero_job_autopilot_records_token_usage_as_unknown(tmp_path):
    database = tmp_path / "state.sqlite"
    run_id = CodexSession(database).intake(title="Simple synthetic", description="Decode this",
                                          categories=["crypto"], paths=[])["run_id"]
    scheduler = AgentScheduler(database, BridgeHost())
    result = autopilot(scheduler, run_id, None, max_waves=1)
    assert result["stop"] == "sequential_work_for_daybreak"
    assert set(result["metrics"]["tokens"].values()) == {"unknown"}
    with sqlite3.connect(database) as db:
        tokens = db.execute("SELECT tokens FROM agent_autopilot_runs WHERE invocation_id=?",
                            (result["metrics"]["invocation_id"],)).fetchone()[0]
    assert json.loads(tokens) == result["metrics"]["tokens"]


def test_autopilot_fails_closed_without_model_turn_reservations(tmp_path):
    scheduler, run = setup_run(tmp_path)
    result = autopilot(scheduler, run, object(), max_waves=1,
                       drive=lambda *args: pytest.fail("unmetered host must not start model work"))
    assert result["stop"] == "host_model_turn_budget_unenforced"
    assert result["budget_enforcement"] == "unavailable"
    assert result["operations"]["dispatch"] == 0
    assert scheduler.model_turn_budget(run) is None
    assert scheduler.jobs(run) == []
    assert result["metrics"]["daybreak_handoffs"] == 1
