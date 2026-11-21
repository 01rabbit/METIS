"""The failure breakdown reproduces the published symmetric-replication totals."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_issue6_failure_breakdown as breakdown


def _result() -> dict:
    return breakdown.analyze(json.loads(breakdown.DATA.read_text(encoding="utf-8")))


def test_totals_match_published_figures() -> None:
    arms = _result()["arms"]
    assert arms["single"]["verified_and_complete"] == 56
    assert arms["single"]["workflow_complete"] == 60
    assert arms["multi"]["workflow_complete"] == 16
    assert arms["multi"]["verified_and_complete"] == 11
    assert sum(arms["multi"]["job_state_pattern"].values()) == 60


def test_failed_trials_partition_and_proxy_is_labelled() -> None:
    result = _result()
    failed = result["multi_failed_trials"]
    assert failed["n"] == 44
    assert failed["oracle_verified_despite_failed_job"] + failed["oracle_not_verified"] == 44
    assert any("failure_category" in f for f in result["missing_fields"])
    assert "at_total_call_cap_PROXY" in failed
