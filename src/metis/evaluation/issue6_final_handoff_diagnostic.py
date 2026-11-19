"""Answer-free paired analysis of the preregistered final-call handoff study."""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

from metis.evaluation.issue6_handoff_diagnostic import _percentile

ARMS = ("single", "multi_combined", "multi_final_handoff")
STUDY = "issue6-final-handoff-diagnostic-2026-11-19"
SEED = 20261120
ORDER_SEED = SEED ^ 0x6A09E667
BOOTSTRAP_SEED = 20261120
BOOTSTRAP_SAMPLES = 10_000
ENCODINGS = ("base64", "base32", "hex", "base85", "base64url", "percent")
CACHED_FIELDS = ("oracle_verified", "elapsed_seconds", "calls_observed", "calls_reserved", "usage",
                 "actions", "synthesis_complete", "job_states", "candidate_ready_jobs", "decision_counts",
                 "report_rejections", "report_rejection_categories", "report_rejection_stages",
                 "terminal_reason_categories", "model_turn_budget_denials", "peer_reserve_denials")


def _interval(deltas: list[int]) -> list[float]:
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = [statistics.mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
                 for _ in range(BOOTSTRAP_SAMPLES)]
    return [round(_percentile(estimates, 0.025), 4), round(_percentile(estimates, 0.975), 4)]


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    if (data.get("study") != STUDY or data.get("seed") != SEED
            or data.get("order_seed") != ORDER_SEED or data.get("arms") != list(ARMS)
            or data.get("repetitions_per_task") != 1 or data.get("distinct_tasks") != 30):
        raise ValueError("study identity or frozen design disagrees with preregistration")
    families = data["encoding_pairs"]
    task_ids = [f"task-{index:02d}" for index in range(30)]
    if set(families) != set(task_ids):
        raise ValueError("expected exactly 30 preregistered task clusters")
    expected_pairs = Counter({tuple(sorted(pair)): 2 for pair in combinations(ENCODINGS, 2)})
    if Counter(tuple(sorted(families[task_id])) for task_id in task_ids) != expected_pairs:
        raise ValueError("encoding families do not match the frozen pair balance")
    cases = [f"{task_id}-rep-0" for task_id in task_ids]
    trial_order = data["trial_order"]
    if (set(trial_order) != set(cases)
            or any(sorted(trial_order[case]) != sorted(ARMS) for case in cases)):
        raise ValueError("trial arm order is incomplete or invalid")
    order_rng = random.Random(ORDER_SEED)
    expected_order = {}
    for case in cases:
        randomized = list(ARMS)
        order_rng.shuffle(randomized)
        expected_order[case] = randomized
    if trial_order != expected_order:
        raise ValueError("trial arm order differs from the preregistered randomization")
    records = data["records"]
    keys = [(record["case"], record["arm"]) for record in records]
    expected_keys = {(case, arm) for case in cases for arm in ARMS}
    if len(keys) != len(expected_keys) or set(keys) != expected_keys:
        raise ValueError("expected exactly one record per case and arm")
    if keys != [(case, arm) for case in cases for arm in trial_order[case]]:
        raise ValueError("record sequence differs from trial order")
    by_key = {(record["case"], record["arm"]): record for record in records}
    comparisons = data["comparisons"]
    if len(comparisons) != len(cases) or {item["case"] for item in comparisons} != set(cases):
        raise ValueError("comparison rows do not cover every case exactly once")
    by_case = {item["case"]: item for item in comparisons}
    outcomes: dict[str, dict[str, bool]] = {}
    completion: dict[str, dict[str, bool]] = {}
    for case in cases:
        task_id = case.rsplit("-rep-", 1)[0]
        comparison = by_case[case]
        if comparison["task_id"] != task_id or set(comparison["arms"]) != set(ARMS):
            raise ValueError("comparison task or arms disagree with records")
        outcomes[case], completion[case] = {}, {}
        for arm in ARMS:
            record = by_key[(case, arm)]
            if record["task_id"] != task_id or record.get("model") != data.get("model") or record.get("cli") != data.get("cli"):
                raise ValueError("record identity disagrees with study")
            cached = comparison["arms"][arm]
            if any(cached.get(field) != record.get(field) for field in CACHED_FIELDS):
                raise ValueError("comparison metric disagrees with retained record")
            jobs = record["job_states"]
            complete = (record["synthesis_complete"] is True and len(jobs) == (1 if arm == "single" else 2)
                        and all(state == "completed" for state in jobs))
            verified = bool(complete and record["oracle_verified"])
            if record["workflow_verified"] != verified:
                raise ValueError("record workflow outcome disagrees with states and oracle")
            completion[case][arm], outcomes[case][arm] = complete, verified

    per_arm: dict[str, Any] = {}
    for arm in ARMS:
        selected = [by_key[(case, arm)] for case in cases]
        known_tokens = all(row["usage_complete"] and isinstance(row["usage"].get("input_tokens"), int)
                           and isinstance(row["usage"].get("output_tokens"), int) for row in selected)
        per_arm[arm] = {
            "trials": 30,
            "workflow_complete_oracle_verified": sum(outcomes[case][arm] for case in cases),
            "workflow_complete": sum(completion[case][arm] for case in cases),
            "oracle_verified": sum(bool(row["oracle_verified"]) for row in selected),
            "mean_elapsed_seconds": round(statistics.mean(row["elapsed_seconds"] for row in selected), 3),
            "mean_calls_observed": round(statistics.mean(row["calls_observed"] for row in selected), 3),
            "mean_calls_reserved": round(statistics.mean(row["calls_reserved"] for row in selected), 3),
            "mean_actions": round(statistics.mean(row["actions"] for row in selected), 3),
            "candidate_ready_jobs_at_termination": sum(row["candidate_ready_jobs"] for row in selected),
            "candidate_ready_call_ceiling_failures": sum(row["candidate_ready_jobs"] > 0
                and not completion[row["case"]][arm] and row["calls_reserved"] >= 8 for row in selected),
            "report_rejections": sum(row["report_rejections"] for row in selected),
            "model_turn_budget_denials": sum(row["model_turn_budget_denials"] for row in selected),
            "decision_counts": dict(sum((Counter(row["decision_counts"]) for row in selected), Counter())),
            "token_usage_complete": known_tokens,
            "mean_input_tokens": (round(statistics.mean(row["usage"]["input_tokens"] for row in selected), 1)
                                  if known_tokens else "unknown"),
            "mean_output_tokens": (round(statistics.mean(row["usage"]["output_tokens"] for row in selected), 1)
                                   if known_tokens else "unknown"),
            "cost_usd": "unknown",
        }

    contrasts: dict[str, dict[str, Any]] = {}
    for reference, name in (("single", "primary_final_minus_single"),
                            ("multi_combined", "mechanism_final_minus_current_multi")):
        left = "multi_final_handoff"
        deltas = [int(outcomes[case][left]) - int(outcomes[case][reference]) for case in cases]
        completion_deltas = [int(completion[case][left]) - int(completion[case][reference]) for case in cases]
        oracle_deltas = [int(bool(by_key[(case, left)]["oracle_verified"]))
                         - int(bool(by_key[(case, reference)]["oracle_verified"])) for case in cases]
        contrasts[name] = {
            "difference": round(statistics.mean(deltas), 4),
            "cluster_bootstrap_95_interval": _interval(deltas),
            "completion_difference": round(statistics.mean(completion_deltas), 4),
            "completion_cluster_bootstrap_95_interval": _interval(completion_deltas),
            "raw_oracle_difference": round(statistics.mean(oracle_deltas), 4),
            "raw_oracle_cluster_bootstrap_95_interval": _interval(oracle_deltas),
            "discordant_pairs": {
                "both": sum(outcomes[case][left] and outcomes[case][reference] for case in cases),
                "left_only": sum(outcomes[case][left] and not outcomes[case][reference] for case in cases),
                "right_only": sum(not outcomes[case][left] and outcomes[case][reference] for case in cases),
                "neither": sum(not outcomes[case][left] and not outcomes[case][reference] for case in cases),
            },
        }
    return {"study": STUDY, "model": data["model"], "cli": data["cli"], "distinct_task_clusters": 30,
            "arms": per_arm, "contrasts": contrasts,
            "primary_gain_gate_met": contrasts["primary_final_minus_single"]["cluster_bootstrap_95_interval"][0] > 0,
            "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED, "resampling_unit": "task_id"},
            "limitations": ["One trial per synthetic task cluster.",
                            "Synthetic encoding tasks do not establish general CTF performance.",
                            "Provider cost is unknown."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        result = analyze(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
