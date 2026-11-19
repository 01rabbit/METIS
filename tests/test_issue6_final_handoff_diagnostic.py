"""Deterministic, answer-free final-call diagnostic checks."""
from __future__ import annotations

import copy
import random
import sys
from itertools import combinations
from pathlib import Path

import pytest

from metis.evaluation.issue6_final_handoff_diagnostic import ARMS, ORDER_SEED, SEED, STUDY, analyze

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_issue6_handoff_diagnostic import call_limits, capped_failures


def test_runner_applies_symmetric_multi_call_caps() -> None:
    assert call_limits("multi_combined", True) == (4, None)
    assert call_limits("multi_final_handoff", True) == (None, 4)
    assert call_limits("single", True) == (None, None)
    assert call_limits("multi_combined", False) == (None, None)


def test_fourth_call_other_failure_is_not_a_ceiling_failure() -> None:
    results = {
        "cap": {"job_state": "failed", "failure": "per-specialist call cap exhausted without completion",
                "codex_turns": [{}, {}, {}, {}]},
        "provider": {"job_state": "failed", "failure": "codex exited 1: provider error",
                     "codex_turns": [{}, {}, {}, {}]},
        "policy": {"job_state": "failed", "failure": "policy_violation: Codex used tools command_execution",
                   "codex_turns": [{}, {}, {}, {}]},
    }
    assert capped_failures(results, "multi_combined") == {"cap"}
    assert capped_failures(results, "multi_final_handoff") == {"cap"}
    assert capped_failures(results, "single") == set()


def dataset() -> dict:
    pairs = list(combinations(("base64", "base32", "hex", "base85", "base64url", "percent"), 2))
    families = {f"task-{index:02d}": list(pairs[index // 2]) for index in range(30)}
    records = []
    comparisons = []
    order = {}
    order_rng = random.Random(ORDER_SEED)
    for index in range(30):
        case = f"task-{index:02d}-rep-0"
        order[case] = list(ARMS)
        order_rng.shuffle(order[case])
        cached = {}
        for arm in order[case]:
            solved = arm == "multi_final_handoff" or (arm == "single" and index < 10)
            row = {
                "case": case, "task_id": f"task-{index:02d}", "arm": arm,
                "model": "fixture-model", "cli": "fixture-cli", "oracle_verified": solved,
                "workflow_verified": solved, "synthesis_complete": solved,
                "job_states": ["completed"] * (1 if arm == "single" else 2) if solved else ["failed"],
                "elapsed_seconds": 1.0, "calls_observed": 2, "calls_reserved": 2,
                "usage": {"input_tokens": 10, "output_tokens": 3}, "usage_complete": arm != "single",
                "actions": 1, "candidate_ready_jobs": 0, "decision_counts": {},
                "report_rejections": 0, "report_rejection_categories": {}, "report_rejection_stages": {},
                "terminal_reason_categories": {}, "model_turn_budget_denials": 0, "peer_reserve_denials": 0,
                "per_specialist_call_ceiling_failures": 0,
                "candidate_ready_per_specialist_call_ceiling_failures": 0,
            }
            records.append(row)
            cached[arm] = {key: row[key] for key in (
                "oracle_verified", "elapsed_seconds", "calls_observed", "calls_reserved", "usage", "actions",
                "synthesis_complete", "job_states", "candidate_ready_jobs", "decision_counts", "report_rejections",
                "report_rejection_categories", "report_rejection_stages", "terminal_reason_categories",
                "model_turn_budget_denials", "peer_reserve_denials",
                "per_specialist_call_ceiling_failures", "candidate_ready_per_specialist_call_ceiling_failures")}
        comparisons.append({"case": case, "task_id": f"task-{index:02d}", "arms": cached})
    return {"study": STUDY, "seed": SEED, "order_seed": ORDER_SEED, "arms": list(ARMS),
            "repetitions_per_task": 1, "distinct_tasks": 30, "encoding_pairs": families,
            "trial_order": order, "records": records, "comparisons": comparisons,
            "model": "fixture-model", "cli": "fixture-cli"}


def test_paired_primary_gate_and_missing_tokens() -> None:
    result = analyze(dataset())
    assert result["bootstrap"] == {"samples": 10_000, "seed": SEED, "resampling_unit": "task_id"}
    assert result["primary_gain_gate_met"] is True
    primary = result["contrasts"]["primary_final_minus_single"]
    assert primary["discordant_pairs"] == {"both": 10, "left_only": 20, "right_only": 0, "neither": 0}
    assert primary["cluster_bootstrap_95_interval"][0] > 0
    assert result["contrasts"]["mechanism_final_minus_current_multi"]["difference"] == 1.0
    assert result["arms"]["single"]["mean_input_tokens"] == "unknown"
    assert result["arms"]["multi_final_handoff"]["mean_output_tokens"] == 3.0
    assert result["arms"]["multi_final_handoff"]["per_specialist_call_ceiling_failures"] == 0
    assert analyze(dataset()) == result


def test_reports_candidate_ready_per_specialist_ceiling() -> None:
    data = dataset()
    row = next(row for row in data["records"] if row["case"] == "task-00-rep-0"
               and row["arm"] == "multi_combined")
    row.update(calls_observed=4, calls_reserved=4, candidate_ready_jobs=1,
               per_specialist_call_ceiling_failures=1,
               candidate_ready_per_specialist_call_ceiling_failures=1)
    cached = data["comparisons"][0]["arms"]["multi_combined"]
    cached.update({key: row[key] for key in ("calls_observed", "calls_reserved", "candidate_ready_jobs",
                                             "per_specialist_call_ceiling_failures",
                                             "candidate_ready_per_specialist_call_ceiling_failures")})
    result = analyze(data)
    assert result["arms"]["multi_combined"]["per_specialist_call_ceiling_failures"] == 1
    assert result["arms"]["multi_combined"]["candidate_ready_per_specialist_call_ceiling_failures"] == 1
    assert result["arms"]["multi_combined"]["candidate_ready_call_ceiling_failures"] == 0


@pytest.mark.parametrize("mutation", [
    lambda data: data["records"].append(copy.deepcopy(data["records"][0])),
    lambda data: data["comparisons"][0]["arms"]["single"].update({"calls_reserved": 9}),
    lambda data: data["trial_order"]["task-00-rep-0"].pop(),
    lambda data: data["encoding_pairs"].pop("task-00"),
    lambda data: data["comparisons"][0]["arms"]["multi_final_handoff"].update(
        {"per_specialist_call_ceiling_failures": 1}),
])
def test_rejects_inconsistent_study(mutation) -> None:
    data = dataset()
    mutation(data)
    with pytest.raises(ValueError):
        analyze(data)
