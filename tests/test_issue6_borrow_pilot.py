"""The borrowing pilot analyzer enforces its frozen answer-free study shape."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.evaluation.issue6_borrow_pilot import SEED, STUDY, analyze

ROOT = Path(__file__).resolve().parents[1]


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


def test_borrow_pilot_rejects_changed_seed_or_arm() -> None:
    data = _fixture()
    data["seed"] += 1
    with pytest.raises(ValueError, match="preregistration"):
        analyze(data)
    data = _fixture()
    data["records"][0]["arm"] = "multi_fixed"
    with pytest.raises(ValueError, match="exactly one result"):
        analyze(data)
