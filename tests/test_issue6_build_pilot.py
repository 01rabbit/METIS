import json
import sqlite3
from dataclasses import asdict

import pytest

from metis.core.codex_specialist import CodexTurn
from metis.evaluation.issue6_build_artifact import canonical_artifact
from metis.evaluation.issue6_build_oracle import BuildFixture, Cause, Job, Observation
from metis.evaluation.issue6_build_pilot import (
    _diagnosis,
    _mac,
    _run_arm,
    run_calibration,
)

FIXTURE = BuildFixture(
    (Job("app", "build", 2),),
    (Cause("slow_job", "app", 2), Cause("slow_job", "app", 4)),
    (Observation("app", "finish", 4),),
)
KEY = bytes(range(32))
NOTE = "private reasoning test sentinel"
INITIAL = '{"option_id":"option-002","work_note":"' + NOTE + '"}'
FINAL = '{"option_id":"option-001"}'


class Scripted:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.prompts = []
        self.schemas = []
        self.timeouts = []

    def run(self, prompt, *, model, timeout, should_stop=None, output_schema=None):
        assert timeout > 0
        assert model == "scripted"
        assert not should_stop()
        self.prompts.append(prompt)
        self.schemas.append(output_schema)
        self.timeouts.append(timeout)
        output = self.turns.pop(0)
        if isinstance(output, BaseException):
            raise output
        if isinstance(output, CodexTurn):
            return output
        return CodexTurn(0, output, usage={"input_tokens": 10, "output_tokens": 2})


def test_matched_phases_share_public_input_and_only_owner_receives_private_note(tmp_path):
    runs = []
    for mode in ("owner_note", "fresh_reviewer"):
        runner = Scripted(INITIAL, FINAL)
        root = tmp_path / mode
        row = _run_arm(root, "opaque", FIXTURE, runner, "scripted", KEY, mode)
        assert row.complete and row.verified and row.actions == row.calls_reserved == 2
        assert row.oracle_checks == 1
        assert all(0 < timeout <= 60 for timeout in runner.timeouts)
        assert row.phases[0].prompt_hmac == _mac(KEY, b"prompt", runner.prompts[0].encode())
        assert row.phases[1].artifact_hmac == _mac(KEY, b"artifact", canonical_artifact(FIXTURE))
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
    runner = Scripted(turn)
    result = _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    assert not result.complete and not result.verified
    assert result.calls_reserved == 1 and result.actions == result.oracle_checks == 0
    assert result.phases[0].outcome == outcome
    assert NOTE not in json.dumps(asdict(result))


def test_interrupted_replay_cannot_start_again_in_the_same_root(tmp_path):
    root = tmp_path / "claim"
    with pytest.raises(RuntimeError, match="interrupted"):
        run_calibration(root, Scripted(RuntimeError("interrupted")), "scripted", KEY)
    assert (root / "claim.json").is_file()
    runner = Scripted()
    with pytest.raises(FileExistsError):
        run_calibration(root, runner, "scripted", KEY)
    assert not runner.prompts


def test_initial_note_has_strict_encoding_bound():
    assert _diagnosis(INITIAL, FIXTURE, initial=True) == ("option-002", NOTE)
    assert _diagnosis(json.dumps({"option_id": "option-001", "work_note": "表" * 129}), FIXTURE, True) is None
    assert _diagnosis(FINAL, FIXTURE, initial=True) is None
    assert _diagnosis(INITIAL, FIXTURE, initial=False) is None


def test_pilot_rehearses_at_most_36_cases_and_keeps_answer_free_receipts(tmp_path):
    runner = Scripted(*[turn for _ in range(36) for turn in (INITIAL, FINAL)])
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
        run_calibration(root, Scripted(), "scripted", KEY)


def test_failed_second_phase_cannot_receive_oracle_credit(tmp_path):
    runner = Scripted(INITIAL, CodexTurn(0, FINAL, timed_out=True))
    result = _run_arm(tmp_path / "arm", "opaque", FIXTURE, runner, "scripted", KEY, "owner_note")
    assert not result.complete and not result.verified
    assert result.oracle_checks == 0 and result.calls_reserved == 2 and result.actions == 1
