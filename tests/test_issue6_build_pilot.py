import json
import sqlite3
from dataclasses import asdict

import pytest

from metis.core.codex_specialist import CodexTurn
from metis.evaluation.issue6_build_artifact import canonical_artifact
from metis.evaluation.issue6_build_oracle import BuildFixture, Cause, Job, Observation
from metis.evaluation.issue6_build_pilot import (
    ScriptedTurns,
    _diagnosis,
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
        assert row.phases[0].prompt_hmac == _mac(KEY, b"prompt", runner.prompts[0].encode())
        assert row.phases[1].artifact_hmac == _mac(KEY, b"artifact", canonical_artifact(FIXTURE, include_submission_rule=False))
        with sqlite3.connect(root / "ledger.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations").fetchone() == (2,)
            assert db.execute("SELECT COUNT(*) FROM issue6_build_pilot_receipts").fetchone() == (2,)
            assert db.execute("SELECT COUNT(*) FROM ctf_agent_reports").fetchone() == (2,)
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


def test_receipt_reconciliation_refuses_equal_count_wrong_reservation(tmp_path):
    root = tmp_path / "arm"
    row = _run_arm(root, "opaque", FIXTURE, ScriptedTurns(INITIAL, FINAL), "scripted", KEY, "owner_note")
    database = root / "ledger.sqlite"
    _reconcile(database, row.run_id, list(row.phases), row.actions)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE issue6_build_pilot_receipts SET reservation = 77 WHERE phase = 1")
    with pytest.raises(RuntimeError, match="does not reconcile"):
        _reconcile(database, row.run_id, list(row.phases), row.actions)
