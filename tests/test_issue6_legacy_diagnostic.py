"""Checks for the frozen, answer-free Issue #6 diagnosis."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.evaluation.issue6_legacy_diagnostic import diagnose

DATA = Path(__file__).resolve().parents[1] / "docs/reports/data/issue6-symmetric-replication-2026-11-18.json"


def test_frozen_diagnosis_separates_oracle_and_completion() -> None:
    result = diagnose(json.loads(DATA.read_text(encoding="utf-8")))
    single = result["arms"]["single"]
    multi = result["arms"]["multi"]
    assert (single["oracle_verified_any_workflow"], single["report_complete"],
            single["report_complete_oracle_verified"]) == (56, 60, 56)
    assert (multi["oracle_verified_any_workflow"], multi["report_complete"],
            multi["report_complete_oracle_verified"]) == (44, 16, 11)
    assert multi["oracle_verified_report_incomplete"] == 33
    assert multi["handoff_failure_observed"] == "unknown"
    assert multi["budget_denial_observed"] == "unknown"


def test_duplicate_and_answer_bearing_records_rejected() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    data["records"].append(dict(data["records"][0]))
    with pytest.raises(ValueError, match="one record"):
        diagnose(data)
    data["records"].pop()
    data["records"][0]["candidate"] = "hidden"
    with pytest.raises(ValueError, match="answer-bearing"):
        diagnose(data)
