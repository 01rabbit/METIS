"""The borrowing pilot analyzer enforces its frozen answer-free study shape."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from metis.evaluation.issue6_borrow_pilot import SEED, STUDY, analyze

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_issue6_borrow_pilot as runner


def _fixture() -> dict:
    source = ROOT / "docs/reports/data/issue6-feasibility-pilot-2026-11-18.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    arm_names = {"single": "single", "multi_separate": "multi_fixed",
                 "multi_combined": "multi_borrow"}
    def rename(value: str) -> str:
        return value.replace("pilot6-", "borrow6-")
    data["study"] = STUDY
    data["seed"] = SEED
    data["order_seed"] = SEED ^ 0x6A09E667
    data["arms"] = list(arm_names.values())
    data["encoding_pairs"] = {rename(key): value for key, value in data["encoding_pairs"].items()}
    data["trial_order"] = {rename(key): [arm_names[arm] for arm in value]
                           for key, value in data["trial_order"].items()}
    for record in data["records"]:
        record["case"] = rename(record["case"])
        record["task_id"] = rename(record["task_id"])
        record["arm"] = arm_names[record["arm"]]
    for row in data["comparisons"]:
        row["case"] = rename(row["case"])
        row["task_id"] = rename(row["task_id"])
        row["arms"] = {arm_names[arm]: value for arm, value in row["arms"].items()}
    return data


def test_borrow_pilot_analyzes_paired_outcomes() -> None:
    result = analyze(_fixture())
    assert result["arms"]["single"]["trials"] == 6
    assert result["arms"]["multi_borrow"]["trials"] == 6
    assert result["primary_gain_gate_met"] is False


def test_committed_trial_data_matches_committed_analysis() -> None:
    directory = ROOT / "docs/reports/data"
    data = json.loads((directory / "issue6-borrow-pilot-2026-11-18.json").read_text(encoding="utf-8"))
    expected = json.loads((directory / "issue6-borrow-pilot-analysis-2026-11-18.json").read_text(encoding="utf-8"))
    result = analyze(data)
    assert result == expected
    assert [result["arms"][arm]["workflow_complete_oracle_verified"]
            for arm in ("single", "multi_fixed", "multi_borrow")] == [5, 1, 3]
    assert result["borrow_minus_single"] == -0.3333
    assert result["borrow_minus_fixed"] == 0.3333


def test_partial_trial_cannot_be_finalized(tmp_path: Path) -> None:
    directory = ROOT / "docs/reports/data"
    data = json.loads((directory / "issue6-borrow-pilot-2026-11-18.json").read_text(encoding="utf-8"))
    output = tmp_path / "final.json"
    with pytest.raises(ValueError, match="18 unique"):
        runner._finalize(data["records"][:-1], data["encoding_pairs"], data["trial_order"], output)
    assert not output.exists()
    runner._finalize(data["records"], data["encoding_pairs"], data["trial_order"], output)
    assert len(json.loads(output.read_text(encoding="utf-8"))["records"]) == 18


def test_borrow_pilot_rejects_changed_seed_or_arm() -> None:
    data = _fixture()
    data["seed"] += 1
    with pytest.raises(ValueError, match="preregistration"):
        analyze(data)
    data = _fixture()
    data["records"][0]["arm"] = "multi_fixed"
    with pytest.raises(ValueError, match="exactly one result"):
        analyze(data)
