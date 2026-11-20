import hashlib
import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexTurn
from metis.evaluation import issue6_build_pilot as pilot
from metis.evaluation import issue6_build_preflight as preflight
from metis.evaluation.issue6_build_artifact import canonical_artifact
from metis.evaluation.issue6_build_oracle import BuildFixture, Cause, Job, Observation
from metis.evaluation.issue6_build_pilot import (
    ScriptedTurns,
    _diagnosis,
    _dispatch_phase,
    _mac,
    _reconcile,
    _run_arm,
    run_calibration,
)
from metis.evaluation.issue6_build_preflight import PilotCodex

FIXTURE = BuildFixture(
    (Job("app", "build", 2),),
    (Cause("slow_job", "app", 2), Cause("slow_job", "app", 4)),
    (Observation("app", "finish", 4),),
)
KEY = bytes(range(32))
NOTE = "private reasoning test sentinel"
INITIAL = '{"option_id":"option-002","work_note":"' + NOTE + '"}'
FINAL = '{"option_id":"option-001"}'


def test_matched_phases_share_public_input_and_only_owner_receives_private_note(tmp_path):
    runs = []
    for mode in ("owner_note", "fresh_reviewer"):
        runner = ScriptedTurns(INITIAL, FINAL)
        root = tmp_path / mode
        row = _run_arm(root, "opaque", FIXTURE, runner, "scripted", KEY, mode)
        assert row.complete and row.verified and row.actions == row.calls_reserved == 2
        assert row.oracle_checks == 1
        assert all(0 < timeout <= 60 for timeout in runner.timeouts)
        assert [item.phase for item in row.phases] == [1, 2]
        assert all(item.assignment_id and item.attempt_id and item.reservation for item in row.phases)
        for receipt, prompt in zip(row.phases, runner.prompts, strict=True):
            assert receipt.prompt_hmac == _mac(KEY, b"prompt", prompt.encode())
            assert receipt.artifact_hmac == _mac(
                KEY, b"artifact", canonical_artifact(FIXTURE, include_submission_rule=False))
        for receipt, schema in zip(row.phases, runner.schemas, strict=True):
            assert receipt.schema_sha256 == hashlib.sha256(
                json.dumps(schema, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
            ).hexdigest()
        with sqlite3.connect(root / "ledger.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (2,)
            assert db.execute("SELECT COUNT(*) FROM issue6_build_pilot_receipts").fetchone() == (2,)
            assert db.execute("SELECT COUNT(*) FROM ctf_agent_reports").fetchone() == (2,)
            joined = db.execute("""
                SELECT turns.id, turns.assignment_id, turns.attempt_id,
                    receipts.assignment_id, receipts.attempt_id, receipts.phase
                FROM agent_turn_reservations turns
                JOIN issue6_build_pilot_receipts receipts
                    ON receipts.run_id=turns.run_id AND receipts.reservation=turns.id
                    AND receipts.assignment_id=turns.assignment_id AND receipts.attempt_id=turns.attempt_id
                WHERE turns.run_id=? ORDER BY turns.id
            """, (row.run_id,)).fetchall()
        assert joined == [
            (item.reservation, item.assignment_id, item.attempt_id,
             item.assignment_id, item.attempt_id, item.phase)
            for item in row.phases
        ]
        for artifact in root.rglob("*"):
            if artifact.is_file():
                assert NOTE.encode() not in artifact.read_bytes()
                assert b"option-001" not in artifact.read_bytes()
        assert NOTE not in json.dumps(asdict(row))
        runs.append(runner)
    owner, fresh = runs
    assert owner.prompts[0] == fresh.prompts[0]
    assert owner.schemas == fresh.schemas
    assert owner.prompts[1].replace('"prior_work_note":"' + NOTE + '",', "") == fresh.prompts[1]
    assert "option-002" in fresh.prompts[1]
    assert NOTE not in fresh.prompts[1]


@pytest.mark.parametrize(
    ("turn", "outcome"),
    [
        (CodexTurn(0, INITIAL, item_types=["command_execution"]), "tool_policy"),
        (CodexTurn(0, INITIAL, tool_errors=["router refused tool"]), "tool_policy"),
        (CodexTurn(0, INITIAL, timed_out=True), "deadline_or_cancelled"),
        (CodexTurn(1, INITIAL, stderr_tail=NOTE), "runtime_failure"),
        (CodexTurn(0, '{"option_id":2.0,"work_note":"invalid"}'), "invalid_response"),
    ],
)
def test_first_phase_failure_stops_without_review_or_oracle(tmp_path, turn, outcome):
    runner = ScriptedTurns(turn)
    result = _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    assert not result.complete and not result.verified
    assert result.calls_reserved == 1 and result.actions == result.oracle_checks == 0
    assert result.phases[0].outcome == outcome
    assert NOTE not in json.dumps(asdict(result))


def test_interrupted_replay_cannot_start_again_in_the_same_root(tmp_path):
    root = tmp_path / "claim"
    with pytest.raises(RuntimeError, match="interrupted"):
        run_calibration(root, ScriptedTurns(None), "scripted", KEY)
    assert (root / "claim.json").is_file()
    database, = root.glob("*/ledger.sqlite")
    with sqlite3.connect(database) as db:
        payload, = db.execute("SELECT payload FROM issue6_build_pilot_receipts").fetchone()
        assert json.loads(payload)["outcome"] == "script_interrupted"
        assert db.execute("SELECT state, failure FROM agent_jobs").fetchone() == (
            "failed", "script_interrupted",
        )
    runner = ScriptedTurns()
    with pytest.raises(FileExistsError):
        run_calibration(root, runner, "scripted", KEY)
    assert not runner.prompts


def test_initial_note_has_strict_encoding_bound():
    assert _diagnosis(INITIAL, FIXTURE, initial=True) == ("option-002", NOTE)
    assert _diagnosis(json.dumps({"option_id": "option-001", "work_note": "表" * 129}), FIXTURE, True) is None
    assert _diagnosis(FINAL, FIXTURE, initial=True) is None
    assert _diagnosis(INITIAL, FIXTURE, initial=False) is None


def test_pilot_rehearses_at_most_36_cases_and_keeps_answer_free_receipts(tmp_path):
    runner = ScriptedTurns(*[turn for _ in range(36) for turn in (INITIAL, FINAL)])
    root = tmp_path / "claim"
    result = run_calibration(root, runner, "scripted", KEY)
    assert len(result["rows"]) == len({row["case_id"] for row in result["rows"]}) == 36
    assert sum(row["calls_reserved"] for row in result["rows"]) <= 72
    assert all(row["complete"] for row in result["rows"])
    assert (root / "completed.json").is_file()
    assert NOTE not in (root / "completed.json").read_text()
    assert "option-001" not in (root / "completed.json").read_text()
    assert result["selected_tier"] is None  # The fixed guess does not pass the pilot threshold.
    with pytest.raises(FileExistsError):
        run_calibration(root, ScriptedTurns(), "scripted", KEY)


def test_failed_second_phase_cannot_receive_oracle_credit(tmp_path):
    runner = ScriptedTurns(INITIAL, CodexTurn(0, FINAL, timed_out=True))
    result = _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    assert not result.complete and not result.verified
    assert result.oracle_checks == 0 and result.calls_reserved == 2 and result.actions == 1


def test_bounded_phase_delivery_value_error_fails_closed(tmp_path, monkeypatch):
    def reject(*_args, **_kwargs):
        raise ValueError("private delivery detail must not be retained")

    monkeypatch.setattr("metis.evaluation.issue6_build_pilot._ScriptedBoundaryHost.deliver_phase", reject)
    runner = ScriptedTurns(INITIAL, FINAL)
    result = _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    assert not result.complete and not result.verified
    assert result.calls_reserved == 1 and result.oracle_checks == 0
    assert result.phases[0].outcome == "prompt_delivery_rejected"
    assert runner.prompts == []
    with sqlite3.connect(tmp_path / "arm" / "ledger.sqlite") as db:
        assert db.execute("SELECT state, failure FROM agent_jobs").fetchone() == (
            "failed", "prompt_delivery_rejected",
        )
        payload, = db.execute("SELECT payload FROM issue6_build_pilot_receipts").fetchone()
        assert "private delivery detail" not in payload


def test_rehearsal_rejects_duck_typed_wrapper_before_claim(tmp_path):
    class ExternalWrapper:
        calls = 0

        def run(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("external wrapper must never be reached")

    wrapper = ExternalWrapper()
    root = tmp_path / "claim"
    with pytest.raises(TypeError, match="built-in scripted"):
        run_calibration(root, wrapper, "scripted", KEY)
    assert not root.exists()
    with pytest.raises(TypeError, match="built-in scripted"):
        _run_arm(root, "opaque", FIXTURE, wrapper, "scripted", KEY, "owner_note")
    assert not root.exists() and wrapper.calls == 0
    with pytest.raises(TypeError, match="fixed response data"):
        ScriptedTurns(wrapper)


def test_pinned_preflight_adapter_cannot_launch_a_model():
    preflight_only = object.__new__(PilotCodex)
    with pytest.raises(RuntimeError, match="offline preflight only"):
        preflight_only.run("must not launch", model="scripted", timeout=1)


def test_phase_output_contract_is_absent_from_common_artifact(tmp_path):
    runner = ScriptedTurns(INITIAL, FINAL)
    _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    both_artifacts = [json.loads(prompt.split("Public fixture: ", 1)[1]) for prompt in runner.prompts]
    assert both_artifacts[0] == both_artifacts[1]
    assert "Return one JSON object" not in both_artifacts[0]["rules"]
    assert set(runner.schemas[0]["required"]) == {"option_id", "work_note"}
    assert runner.schemas[1]["required"] == ["option_id"]
    assert "private work_note" in runner.prompts[0]


@pytest.mark.parametrize("tamper", ["reservation", "assignment", "attempt", "delete"])
def test_receipt_reconciliation_refuses_wrong_or_missing_join(tmp_path, tamper):
    root = tmp_path / "arm"
    row = _run_arm(root, "opaque", FIXTURE, ScriptedTurns(INITIAL, FINAL), "scripted", KEY, "owner_note")
    database = root / "ledger.sqlite"
    _reconcile(database, row.run_id, list(row.phases), row.actions)
    with sqlite3.connect(database) as db:
        if tamper == "reservation":
            db.execute("UPDATE issue6_build_pilot_receipts SET reservation = 77 WHERE phase = 1")
        elif tamper == "assignment":
            db.execute("UPDATE issue6_build_pilot_receipts SET assignment_id = 'wrong' WHERE phase = 1")
        elif tamper == "attempt":
            db.execute("UPDATE issue6_build_pilot_receipts SET attempt_id = 'wrong' WHERE phase = 1")
        else:
            db.execute("DELETE FROM issue6_build_pilot_receipts WHERE phase = 1")
    with pytest.raises(RuntimeError, match="does not reconcile"):
        _reconcile(database, row.run_id, list(row.phases), row.actions)


def test_initial_receipt_insert_failure_rolls_back_turn_reservation(tmp_path, monkeypatch):
    root = tmp_path / "arm"
    runner = ScriptedTurns(INITIAL, FINAL)

    def fail_insert(_db, _run_id, _receipt):
        raise RuntimeError("injected receipt persistence failure")

    monkeypatch.setattr("metis.evaluation.issue6_build_pilot._insert_receipt", fail_insert)
    with pytest.raises(RuntimeError, match="injected receipt persistence failure"):
        _run_arm(root, "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")

    with sqlite3.connect(root / "ledger.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (0,)
        assert db.execute("SELECT turns_reserved FROM agent_run_turn_budgets").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM issue6_build_pilot_receipts").fetchone() == (0,)
        assert db.execute("SELECT state FROM agent_jobs").fetchone() == ("failed",)
    assert runner.prompts == []


def test_later_receipt_insert_failure_preserves_only_prior_turns(tmp_path, monkeypatch):
    root = tmp_path / "arm"
    runner = ScriptedTurns(INITIAL, FINAL)
    insert_receipt = pilot._insert_receipt
    insert_count = 0

    def fail_second_insert(db, run_id, receipt):
        nonlocal insert_count
        insert_count += 1
        if insert_count == 2:
            raise RuntimeError("injected second-phase receipt failure")
        insert_receipt(db, run_id, receipt)

    monkeypatch.setattr(pilot, "_insert_receipt", fail_second_insert)
    with pytest.raises(RuntimeError, match="injected second-phase receipt failure"):
        _run_arm(root, "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")

    with sqlite3.connect(root / "ledger.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (1,)
        assert db.execute("SELECT turns_reserved FROM agent_run_turn_budgets").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM issue6_build_pilot_receipts").fetchone() == (1,)
        reservation, assignment, attempt, phase, payload = db.execute(
            "SELECT turns.id,turns.assignment_id,turns.attempt_id,receipts.phase,receipts.payload "
            "FROM agent_turn_reservations turns JOIN issue6_build_pilot_receipts receipts "
            "ON receipts.run_id=turns.run_id AND receipts.reservation=turns.id "
            "AND receipts.assignment_id=turns.assignment_id AND receipts.attempt_id=turns.attempt_id "
            "ORDER BY turns.id"
        ).fetchone()
        prior_receipt = json.loads(payload)
        assert (phase, prior_receipt["phase"], prior_receipt["reservation"],
                prior_receipt["assignment_id"], prior_receipt["attempt_id"],
                prior_receipt["outcome"]) == (
            1, 1, reservation, assignment, attempt, "accepted",
        )
        assert db.execute(
            "SELECT state FROM agent_jobs WHERE assignment_id=? AND attempt_id=?",
            (assignment, attempt),
        ).fetchone() == ("completed",)
        assert db.execute("SELECT COUNT(*) FROM agent_jobs WHERE state='failed'").fetchone() == (1,)
    assert len(runner.prompts) == 1


def _queued_scheduler_run(scheduler, session, artifact: Path, title: str):
    run_id = session.intake(title=title, description="Public synthetic fixture.", paths=[artifact],
                            categories=["misc"], max_actions=2, wall_seconds=120,
                            evaluation_split="practice")["run_id"]
    wave = scheduler.ledger.create_wave(run_id, mode="delegated", plan_policy=_one_artifact_plan)
    scheduler.enqueue(run_id, wave["wave_id"])
    return run_id


def _one_artifact_plan(plan):
    assignments = [item for item in plan["assignments"] if item["role"] == "artifact-triage"]
    assignments = assignments[:1]
    if not assignments:
        raise RuntimeError("missing artifact-triage assignment")
    assignments[0]["max_turns"] = 1
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = ["artifact-triage"]
    plan["daybreak_covers"] = []
    return plan


def _two_artifact_plan(plan):
    plan = _one_artifact_plan(plan)
    first = plan["assignments"][0]
    second = dict(first)
    second["objective"] = "Check the same synthetic input independently."
    plan["assignments"] = [first, second]
    plan["decision"]["required_roles"] = ["artifact-triage", "artifact-triage"]
    return plan


def test_dispatch_preflight_refuses_when_model_call_budget_is_short(tmp_path):
    host = FakeHost(max_parallel=1)
    scheduler = AgentScheduler(tmp_path / "ledger.sqlite", host)
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=1,
                        catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted",
                        memory_retrieval=False)
    source = tmp_path / "fixture.json"
    source.write_bytes(canonical_artifact(FIXTURE, include_submission_rule=False))
    session = CodexSession(scheduler.database)
    run_id = _queued_scheduler_run(scheduler, session, source, "Budget refusal")
    with pytest.raises(ValueError, match="insufficient model-call budget"):
        _dispatch_phase(scheduler, run_id, required_calls=2)
    assert host.spawned == []
    assert all(job["state"] == "queued" for job in scheduler.jobs(run_id))


def test_dispatch_preflight_refuses_when_global_slot_is_busy(tmp_path):
    host = FakeHost(max_parallel=1)
    scheduler = AgentScheduler(tmp_path / "ledger.sqlite", host)
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=2,
                        catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted",
                        memory_retrieval=False)
    session = CodexSession(scheduler.database)
    source = tmp_path / "fixture.json"
    source.write_bytes(canonical_artifact(FIXTURE, include_submission_rule=False))
    active_run = _queued_scheduler_run(scheduler, session, source, "Occupying run")
    assert len(scheduler.dispatch(active_run)["started"]) == 1
    spawned_before = list(host.spawned)
    queued_run = _queued_scheduler_run(scheduler, session, source, "Queued run")
    with pytest.raises(ValueError, match="no dispatch slot"):
        _dispatch_phase(scheduler, queued_run, required_calls=1)
    assert host.spawned == spawned_before
    assert all(job["state"] == "queued" for job in scheduler.jobs(queued_run))


def test_dispatch_preflight_refuses_when_per_run_slot_is_busy(tmp_path):
    host = FakeHost(max_parallel=2)
    scheduler = AgentScheduler(tmp_path / "ledger.sqlite", host)
    scheduler.configure(global_slots=2, per_run_slots=1, specialist_turn_budget=2,
                        catalog=[{"id": "scripted", "tier": "standard"}], current_model="scripted",
                        memory_retrieval=False)
    source = tmp_path / "fixture.json"
    source.write_bytes(canonical_artifact(FIXTURE, include_submission_rule=False))
    session = CodexSession(scheduler.database)
    run_id = session.intake(title="Per-run slot refusal", description="Public synthetic fixture.",
                            paths=[source], categories=["misc"], max_actions=2,
                            wall_seconds=120, evaluation_split="practice")["run_id"]
    wave = scheduler.ledger.create_wave(run_id, mode="delegated", plan_policy=_two_artifact_plan)
    scheduler.enqueue(run_id, wave["wave_id"])
    first = scheduler.dispatch(run_id)
    assert len(first["started"]) == 1 and first["queued"] == 1
    spawned_before = list(host.spawned)
    with pytest.raises(ValueError, match="no dispatch slot"):
        _dispatch_phase(scheduler, run_id, required_calls=1)
    assert host.spawned == spawned_before
    assert sorted(job["state"] for job in scheduler.jobs(run_id)) == ["queued", "running"]


def test_unpinned_executable_is_never_invoked(tmp_path, monkeypatch):
    sentinel = tmp_path / "executed"
    executable = tmp_path / "codex"
    executable.write_text(f'#!/bin/sh\ntouch "{sentinel}"\n')
    executable.chmod(0o700)
    monkeypatch.setattr(preflight, "NATIVE_SIZE", executable.stat().st_size)

    def must_not_run(*args, **kwargs):
        pytest.fail("an executable was invoked before pin validation")

    monkeypatch.setattr(preflight.subprocess, "run", must_not_run)
    with pytest.raises(RuntimeError, match="pinned native Codex binary"):
        preflight.offline_preflight(executable)
    assert not sentinel.exists()


def test_preflight_probes_same_verified_copy_under_minimal_seatbelt(tmp_path, monkeypatch):
    original = tmp_path / "native"
    content = b"pinned test bytes"
    original.write_bytes(content)
    monkeypatch.setattr(preflight, "NATIVE_SIZE", len(content))
    monkeypatch.setattr(preflight, "NATIVE_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(preflight, "isolation_backend", lambda: "seatbelt")
    monkeypatch.setattr(preflight, "self_test", lambda *args, **kwargs: {"passed": True})
    probes = []

    def wrap(backend, *, turn_dir, argv, env, proxy, readable, protected, workdir, executable):
        assert backend == "seatbelt" and not proxy.hosts
        assert executable.read_bytes() == content and executable != original
        assert readable == [executable] and workdir == turn_dir
        assert argv[0] == str(executable)
        assert env == {"PATH": "/usr/bin:/bin", "HOME": str(turn_dir), "CODEX_HOME": str(turn_dir), "LANG": "C"}
        probes.append((executable, argv[1:]))
        return ["sandbox", *argv], env

    def run(command, **kwargs):
        assert command[0] == "sandbox"
        output = b"codex-cli 0.169.0" if command[-1] == "--version" else b"shell_tool stable true"
        return subprocess.CompletedProcess(command, 0, output)

    monkeypatch.setattr(preflight, "wrap", wrap)
    monkeypatch.setattr(preflight.subprocess, "run", run)
    result = preflight.offline_preflight(original)
    assert len(probes) == 2 and probes[0][0] == probes[1][0]
    assert [args for _, args in probes] == [["--version"], ["features", "list"]]
    assert result["network_model_calls"] == 0
