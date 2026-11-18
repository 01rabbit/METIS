"""Validate answer-free action-reserved conditional pilot records."""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

STUDY = "issue6-conditional-reserve-pilot-2026-11-18"
SEED = 2026111829
ORDER_SEED = SEED ^ 0x6A09E667
ARMS = ("single", "conditional")
PAIR_COUNTS = {tuple(sorted(pair)): 2 for pair in (
    ("base64", "base32"), ("base64", "hex"), ("base64", "base85"),
    ("base32", "hex"), ("base32", "percent"), ("hex", "base85"))}


def _interval(deltas: list[int]) -> list[float]:
    rng = random.Random(20261119)
    estimates = sorted(statistics.mean(rng.choice(deltas) for _ in deltas) for _ in range(10_000))
    return [round(estimates[249], 4), round(estimates[9749], 4)]


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    families = data.get("encoding_pairs")
    if (data.get("study") != STUDY or data.get("seed") != SEED
            or data.get("order_seed") != ORDER_SEED or data.get("arms") != list(ARMS)
            or not isinstance(families, dict)
            or sorted(families) != [f"reserve12-{index:02d}" for index in range(12)]
            or Counter(tuple(sorted(pair)) for pair in families.values()) != PAIR_COUNTS):
        raise ValueError("conditional pilot disagrees with preregistration")
    cases = {f"{task_id}-rep-0" for task_id in families}
    order = data.get("trial_order")
    order_rng = random.Random(ORDER_SEED)
    expected_order: dict[str, list[str]] = {}
    for case in sorted(cases):
        shuffled = list(ARMS)
        order_rng.shuffle(shuffled)
        expected_order[case] = shuffled
    if (not isinstance(order, dict) or set(order) != cases
            or order != expected_order):
        raise ValueError("conditional pilot trial order is incomplete")
    records = data.get("records")
    if not isinstance(records, list):
        raise TypeError("conditional pilot records are missing")
    keys = [(row["case"], row["arm"]) for row in records]
    if len(keys) != 24 or len(set(keys)) != 24 or set(keys) != {(case, arm) for case in cases for arm in ARMS}:
        raise ValueError("conditional pilot requires 24 unique case-arm records")
    by_key = {(row["case"], row["arm"]): row for row in records}
    comparisons = data.get("comparisons")
    if (not isinstance(comparisons, list) or len(comparisons) != 12
            or {row["case"] for row in comparisons} != cases):
        raise ValueError("conditional pilot comparisons are incomplete")
    by_case = {row["case"]: row for row in comparisons}
    for case in cases:
        if (by_case[case]["task_id"] != case.rsplit("-rep-", 1)[0]
                or set(by_case[case]["arms"]) != set(ARMS)):
            raise ValueError("conditional pilot comparisons disagree with records")
        for arm in ARMS:
            source = by_key[(case, arm)]
            cached = by_case[case]["arms"][arm]
            if any(cached.get(key) != source.get(key) for key in (
                    "oracle_verified", "calls_observed", "calls_reserved", "elapsed_seconds", "actions")):
                raise ValueError("conditional pilot comparison metrics disagree with records")
    for row in records:
        if (row["task_id"] != row["case"].rsplit("-rep-", 1)[0]
                or row["model"] != data["model"] or row["cli"] != data["cli"]
                or row["model"] != "gpt-6.1-sol" or row["cli"] != "0.169.0"
                or row["reasoning_effort"] != "low" or row["actions"] > 4
                or row["calls_reserved"] > 8
                or row["workflow_verified"] != (row["oracle_verified"] is True
                                                and row["verified_assignment_state"] == "completed")):
            raise ValueError("conditional pilot record is inconsistent")
        if row["arm"] == "single" and (row["fallback_dispatched"] or len(row["job_states"]) != 1):
            raise ValueError("single arm has invalid job states")
        if row["arm"] == "conditional" and len(row["job_states"]) != (2 if row["fallback_dispatched"] else 1):
            raise ValueError("conditional arm has invalid fallback states")
    deltas = [int(by_key[(case, "conditional")]["workflow_verified"])
              - int(by_key[(case, "single")]["workflow_verified"]) for case in sorted(cases)]
    return {
        "study": STUDY,
        "trials": 12,
        "workflow_verified": {arm: sum(by_key[(case, arm)]["workflow_verified"] for case in cases)
                              for arm in ARMS},
        "raw_oracle_verified": {arm: sum(by_key[(case, arm)]["oracle_verified"] for case in cases)
                                for arm in ARMS},
        "fallback_dispatched": sum(by_key[(case, "conditional")]["fallback_dispatched"] for case in cases),
        "conditional_minus_single": round(statistics.mean(deltas), 4),
        "cluster_bootstrap_95_interval": _interval(deltas),
        "discordant_pairs": {
            "conditional_only": deltas.count(1), "single_only": deltas.count(-1),
            "both_or_neither": deltas.count(0),
        },
        "mean_calls_reserved": {
            arm: round(statistics.mean(by_key[(case, arm)]["calls_reserved"] for case in cases), 3)
            for arm in ARMS},
        "mean_actions": {
            arm: round(statistics.mean(by_key[(case, arm)]["actions"] for case in cases), 3)
            for arm in ARMS},
        "mean_elapsed_seconds": {
            arm: round(statistics.mean(by_key[(case, arm)]["elapsed_seconds"] for case in cases), 3)
            for arm in ARMS},
        "report_rejections": {arm: sum(by_key[(case, arm)]["report_rejections"] for case in cases)
                              for arm in ARMS},
        "model_turn_budget_denials": {
            arm: sum(by_key[(case, arm)]["model_turn_budget_denials"] for case in cases)
            for arm in ARMS},
        "token_usage_complete": {arm: all(by_key[(case, arm)]["usage_complete"] for case in cases)
                                 for arm in ARMS},
        "input_tokens": {
            arm: (sum(by_key[(case, arm)]["usage"]["input_tokens"] for case in cases)
                  if all(by_key[(case, arm)]["usage_complete"] for case in cases) else "unknown")
            for arm in ARMS},
        "output_tokens": {
            arm: (sum(by_key[(case, arm)]["usage"]["output_tokens"] for case in cases)
                  if all(by_key[(case, arm)]["usage_complete"] for case in cases) else "unknown")
            for arm in ARMS},
        "primary_positive": statistics.mean(deltas) > 0,
        "p5_gate_met": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(json.loads(args.input.read_text(encoding="utf-8"))), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
