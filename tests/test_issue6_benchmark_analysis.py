import pytest

from metis.evaluation.issue6_diverse_analysis import analyze


def fixture_result() -> dict:
    tasks = {f"task-{index:02d}": ["base64", "hex"] for index in range(30)}
    pairs = []
    records = []
    for task_id in tasks:
        for repetition in range(2):
            case = f"{task_id}-rep-{repetition}"
            pairs.append({
                "case": case,
                "single_verified": False,
                "multi_verified": True,
                "single_seconds": 2.0,
                "multi_seconds": 1.0,
                "single_calls": 4,
                "multi_calls": 6,
                "single_actions": 2,
                "multi_actions": 3,
                "single_tokens": {"input_tokens": 10, "output_tokens": 2},
                "multi_tokens": {"input_tokens": 15, "output_tokens": 3},
            })
            for arm in ("single", "multi"):
                records.append({
                    "case": case,
                    "arm": arm,
                    "calls_reserved": 4 if arm == "single" else 6,
                    "calls_observed": 4 if arm == "single" else 6,
                    "actions": 2 if arm == "single" else 3,
                    "usage_complete": True,
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "synthesis_complete": True,
                    "job_states": ["completed"] * (1 if arm == "single" else 2),
                })
    return {
        "study": "issue6-diverse-real-model-benchmark",
        "model": "gpt-6.1-sol",
        "cli": "0.169.0",
        "reasoning_effort": "low",
        "encoding_pairs": tasks,
        "pairs": pairs,
        "records": records,
    }


def test_analysis_bootstraps_task_clusters_and_reports_paired_outcomes():
    result = analyze(fixture_result())
    assert result["distinct_task_clusters"] == 30
    assert result["repetitions_per_cluster"] == 2
    assert result["arms"]["single"]["oracle_verified"] == 0
    assert result["arms"]["multi"]["oracle_verified"] == 60
    assert result["arms"]["multi"]["protocol_complete_oracle_verified"] == 60
    assert result["arms"]["single"]["usage_complete_for_all_trials"] is True
    assert result["discordant_pairs"] == {"multi_only": 60}
    assert result["paired_solve_difference_cluster_bootstrap_95_percentile_interval"] == [1.0, 1.0]
    assert result["paired_latency_difference_cluster_bootstrap_95_percentile_interval_seconds"] == [1.0, 1.0]
    assert len(result["failures"]) == 60


def test_analysis_rejects_incomplete_or_unpaired_input():
    data = fixture_result()
    data["pairs"].pop()
    with pytest.raises(ValueError, match="paired case|30 task clusters"):
        analyze(data)


def test_analysis_marks_vacuous_or_empty_usage_as_unknown():
    data = fixture_result()
    data["records"][0]["calls_observed"] = 0
    data["records"][0]["usage"] = {}
    result = analyze(data)
    assert result["arms"]["single"]["usage_complete_for_all_trials"] is False
    assert result["arms"]["single"]["mean_input_tokens_reported"] == "unknown"


def test_analysis_separates_oracle_candidate_from_complete_workflow():
    data = fixture_result()
    data["records"][1]["job_states"] = ["failed"]
    data["records"][1]["synthesis_complete"] = False
    result = analyze(data)
    assert result["arms"]["multi"]["oracle_verified"] == 60
    assert result["arms"]["multi"]["protocol_complete_trials"] == 59
    assert result["arms"]["multi"]["protocol_complete_oracle_verified"] == 59
    assert result["arms"]["multi"]["oracle_verified_but_protocol_incomplete"] == 1


def test_analysis_reports_job_state_patterns_for_incomplete_multi_workflow():
    data = fixture_result()
    data["records"][1]["job_states"] = ["failed", "completed"]
    data["records"][1]["synthesis_complete"] = False
    result = analyze(data)
    assert result["arms"]["multi"]["job_state_patterns"]["failed,completed"] == 1
    assert result["arms"]["multi"]["job_state_patterns"]["completed,completed"] == 59


@pytest.mark.parametrize("arm_index,states", [(0, []), (1, []), (1, ["completed"])])
def test_analysis_requires_exact_assigned_job_count(arm_index, states):
    data = fixture_result()
    data["records"][arm_index]["job_states"] = states
    result = analyze(data)
    arm = "single" if arm_index == 0 else "multi"
    assert result["arms"][arm]["protocol_complete_trials"] == 59


@pytest.mark.parametrize("mutation", ["duplicate_record", "missing_record", "duplicate_pair"])
def test_analysis_rejects_duplicate_or_missing_evidence(mutation):
    data = fixture_result()
    if mutation == "duplicate_record":
        data["records"].append(data["records"][0].copy())
    elif mutation == "missing_record":
        data["records"].pop()
    else:
        # Previously two copies of rep-0 satisfied the two-repetition count.
        data["pairs"][1] = data["pairs"][0].copy()
    with pytest.raises(ValueError):
        analyze(data)
