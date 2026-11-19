"""Deterministic, answer-free final-call diagnostic checks."""
from __future__ import annotations

import copy
import random
from itertools import combinations

import pytest

from metis.evaluation.issue6_final_handoff_diagnostic import ARMS, ORDER_SEED, SEED, STUDY, analyze


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
            }
            records.append(row)
            cached[arm] = {key: row[key] for key in (
                "oracle_verified", "elapsed_seconds", "calls_observed", "calls_reserved", "usage", "actions",
                "synthesis_complete", "job_states", "candidate_ready_jobs", "decision_counts", "report_rejections",
                "report_rejection_categories", "report_rejection_stages", "terminal_reason_categories",
                "model_turn_budget_denials", "peer_reserve_denials")}
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
    assert analyze(dataset()) == result


@pytest.mark.parametrize("mutation", [
    lambda data: data["records"].append(copy.deepcopy(data["records"][0])),
    lambda data: data["comparisons"][0]["arms"]["single"].update({"calls_reserved": 9}),
    lambda data: data["trial_order"]["task-00-rep-0"].pop(),
    lambda data: data["encoding_pairs"].pop("task-00"),
])
def test_rejects_inconsistent_study(mutation) -> None:
    data = dataset()
    mutation(data)
    with pytest.raises(ValueError):
        analyze(data)
