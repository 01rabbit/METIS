"""Analyze the preregistered Issue #6 paired synthetic benchmark output."""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20261118


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def cluster_interval(rows: list[dict[str, Any]], task_ids: list[str],
                     value: str, *, samples: int = BOOTSTRAP_SAMPLES) -> list[float]:
    by_task: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in task_ids}
    for row in rows:
        by_task[row["task_id"]].append(row)
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = []
    for _ in range(samples):
        selected = [rng.choice(task_ids) for _ in task_ids]
        observation = [row[value] for task_id in selected for row in by_task[task_id]]
        estimates.append(statistics.mean(observation))
    return [round(percentile(estimates, 0.025), 4), round(percentile(estimates, 0.975), 4)]


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    task_families = data["encoding_pairs"]
    task_ids = sorted(task_families)
    rows = []
    for pair in data["pairs"]:
        task_id = pair["case"].rsplit("-rep-", 1)[0]
        row = {
            "task_id": task_id,
            "single_verified": bool(pair["single_verified"]),
            "multi_verified": bool(pair["multi_verified"]),
            "solve_delta_multi_minus_single": int(pair["multi_verified"]) - int(pair["single_verified"]),
            "latency_delta_single_minus_multi": float(pair["single_seconds"]) - float(pair["multi_seconds"]),
            "single_seconds": float(pair["single_seconds"]),
            "multi_seconds": float(pair["multi_seconds"]),
            "single_calls": int(pair["single_calls"]),
            "multi_calls": int(pair["multi_calls"]),
            "single_actions": int(pair["single_actions"]),
            "multi_actions": int(pair["multi_actions"]),
            "single_tokens": pair["single_tokens"],
            "multi_tokens": pair["multi_tokens"],
        }
        rows.append(row)
    if len(rows) != 60 or len(task_ids) != 30 or any(
            sum(row["task_id"] == task_id for row in rows) != 2 for task_id in task_ids):
        raise ValueError("expected 30 task clusters with exactly two paired repetitions each")

    outcomes: Counter[str] = Counter()
    for row in rows:
        if row["multi_verified"] and row["single_verified"]:
            outcomes["both"] += 1
        elif row["multi_verified"]:
            outcomes["multi_only"] += 1
        elif row["single_verified"]:
            outcomes["single_only"] += 1
        else:
            outcomes["neither"] += 1

    records_by_key = {(record["case"], record["arm"]): record for record in data["records"]}
    failures = []
    for pair in data["pairs"]:
        if pair["single_verified"] and pair["multi_verified"]:
            continue
        task_id = pair["case"].rsplit("-rep-", 1)[0]
        failure = {
            "case": pair["case"],
            "encoding_pair": task_families[task_id],
            "single_verified": pair["single_verified"],
            "multi_verified": pair["multi_verified"],
        }
        for arm in ("single", "multi"):
            record = records_by_key[(pair["case"], arm)]
            failure[f"{arm}_calls"] = record["calls_observed"]
            failure[f"{arm}_actions"] = record["actions"]
            failure[f"{arm}_synthesis_complete"] = record["synthesis_complete"]
            failure[f"{arm}_job_states"] = record["job_states"]
        failures.append(failure)

    solve_delta = statistics.mean(row["solve_delta_multi_minus_single"] for row in rows)
    latency_delta = statistics.mean(row["latency_delta_single_minus_multi"] for row in rows)
    arms = {}
    for arm in ("single", "multi"):
        arm_records = [record for record in data["records"] if record["arm"] == arm]
        complete_usage_records = [record for record in arm_records
                                  if record.get("usage_complete") is True
                                  and record["calls_observed"] > 0
                                  and record["usage"]["input_tokens"] > 0
                                  and record["usage"]["output_tokens"] > 0]
        usage_complete = len(complete_usage_records) == len(arm_records)
        arms[arm] = {
            "oracle_verified": sum(row[f"{arm}_verified"] for row in rows),
            "trials": len(rows),
            "mean_end_to_end_seconds": round(statistics.mean(row[f"{arm}_seconds"] for row in rows), 3),
            "mean_wall_budget_fraction": round(statistics.mean(row[f"{arm}_seconds"] for row in rows) / 600, 4),
            "mean_calls_observed": round(statistics.mean(row[f"{arm}_calls"] for row in rows), 3),
            "mean_calls_reserved": round(statistics.mean(record["calls_reserved"] for record in arm_records), 3),
            "mean_observed_call_budget_fraction": round(
                statistics.mean(row[f"{arm}_calls"] for row in rows) / 8, 4),
            "mean_actions": round(statistics.mean(row[f"{arm}_actions"] for row in rows), 3),
            "mean_action_budget_fraction": round(statistics.mean(
                row[f"{arm}_actions"] for row in rows) / 4, 4),
            "usage_complete_trials_reported": len(complete_usage_records),
            "usage_complete_for_all_trials": usage_complete,
            "mean_input_tokens_reported": (round(statistics.mean(
                row[f"{arm}_tokens"]["input_tokens"] for row in rows), 1)
                if usage_complete else "unknown"),
            "mean_output_tokens_reported": (round(statistics.mean(
                row[f"{arm}_tokens"]["output_tokens"] for row in rows), 1)
                if usage_complete else "unknown"),
        }
    return {
        "study": data["study"],
        "model": data["model"],
        "cli": data["cli"],
        "reasoning_effort": data["reasoning_effort"],
        "distinct_task_clusters": len(task_ids),
        "repetitions_per_cluster": 2,
        "arms": arms,
        "discordant_pairs": dict(outcomes),
        "paired_mean_solve_difference_multi_minus_single": round(solve_delta, 4),
        "paired_solve_difference_cluster_bootstrap_95_percentile_interval": cluster_interval(
            rows, task_ids, "solve_delta_multi_minus_single"),
        "paired_mean_latency_difference_single_minus_multi_seconds": round(latency_delta, 3),
        "paired_latency_difference_cluster_bootstrap_95_percentile_interval_seconds": cluster_interval(
            rows, task_ids, "latency_delta_single_minus_multi"),
        "bootstrap": {"resampling_unit": "task_id; retain both repetitions",
                      "samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
        "cost_usd": "unknown",
        "failures": failures,
        "limitations": [
            "Synthetic short-text decoding only; no general CTF or AlpacaHack solve-rate claim.",
            "Elapsed time is end-to-end controller time, including setup, synthesis, cleanup, and verification.",
            "Role prompt and decomposition differences are bundled in the two-arm comparison.",
            "Token totals are the runner-reported aggregates; provider cost remains unknown.",
        ],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: analyze_issue6_diverse_results.py FINAL_RESULT.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        summary = analyze(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"benchmark result analysis failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
