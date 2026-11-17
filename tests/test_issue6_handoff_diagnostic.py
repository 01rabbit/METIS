from __future__ import annotations

import copy

import pytest

from metis.evaluation.issue6_handoff_diagnostic import ARMS, analyze


def _dataset() -> dict:
    tasks = {f"task-{index:02d}": ["base64", "hex"] for index in range(30)}
    records = []
    comparisons = []
    for task_index, task_id in enumerate(tasks):
        case = f"{task_id}-rep-0"
        by_arm = {}
        for arm in ARMS:
            multi = arm != "single"
            verified = arm == "multi_combined" and task_index == 0
            record = {
                "case": case, "task_id": task_id, "arm": arm,
                "oracle_verified": verified, "elapsed_seconds": 10.0,
                "calls_observed": 4 if multi else 2, "calls_reserved": 4 if multi else 2,
                "usage": {"input_tokens": 20, "output_tokens": 2}, "usage_complete": True,
                "actions": 1, "synthesis_complete": True,
                "job_states": ["completed", "completed"] if multi else ["completed"],
                "candidate_ready_jobs": 0, "decision_counts": {"report": 1},
                "report_rejections": 0,
                "report_rejection_categories": {"candidate_disclosure": 0, "other_validation": 0},
                "terminal_reason_categories": {"completed": 2 if multi else 1},
                "model_turn_budget_denials": 0,
            }
            records.append(record)
            by_arm[arm] = {key: record[key] for key in (
                "oracle_verified", "elapsed_seconds", "calls_observed", "calls_reserved", "usage", "actions",
                "synthesis_complete", "job_states", "candidate_ready_jobs", "decision_counts",
                "report_rejections", "report_rejection_categories", "terminal_reason_categories",
                "model_turn_budget_denials")}
        comparisons.append({"case": case, "task_id": task_id, "arms": by_arm})
    return {"study": "test", "model": "model", "cli": "0.0", "reasoning_effort": "low",
            "seed": 1, "order_seed": 2, "distinct_tasks": 30, "repetitions_per_task": 1,
            "encoding_pairs": tasks, "trial_order": {}, "records": records,
            "comparisons": comparisons, "arms": list(ARMS), "retained_content": "answer-free"}


def test_analyze_three_arm_handoff_diagnostic_uses_task_clusters() -> None:
    result = analyze(_dataset())

    assert result["distinct_task_clusters"] == 30
    assert result["arms"]["multi_combined"]["workflow_complete_oracle_verified"] == 1
    assert result["primary_contrast_multi_combined_minus_single"] == pytest.approx(1 / 30, abs=0.0001)
    assert result["primary_gain_gate_met"] is False
    assert result["bootstrap"]["resampling_unit"] == "task_id"
    assert result["discordant_pairs"]["combined_vs_separate"]["left_only"] == 1


def test_analyze_rejects_duplicate_arm_record() -> None:
    data = _dataset()
    data["records"].append(copy.deepcopy(data["records"][0]))

    with pytest.raises(ValueError, match="exactly one result"):
        analyze(data)


def test_analyze_rejects_wrong_task_count() -> None:
    data = _dataset()
    data["encoding_pairs"].pop("task-29")

    with pytest.raises(ValueError, match="30 new task clusters"):
        analyze(data)
