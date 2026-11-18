"""Answer-free analysis for the Issue #6 candidate/report diagnostic."""
from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

ARMS = ("single", "multi_separate", "multi_combined")
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20261119


@dataclass(frozen=True)
class StudyShape:
    """Frozen study identity supplied by the caller, outside generic analysis."""

    study: str
    seed: int
    order_seed: int
    task_ids: tuple[str, ...]
    pair_counts: tuple[tuple[tuple[str, str], int], ...]


PILOT_SHAPE = StudyShape(
    study="issue6-feasibility-pilot-2026-11-18",
    seed=2026111806,
    order_seed=2026111806 ^ 0x6A09E667,
    task_ids=tuple(f"pilot6-{index:02d}" for index in range(6)),
    pair_counts=((('base32', 'base64'), 2), (('base64', 'hex'), 2),
                 (('base64', 'base85'), 2)),
)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _cluster_interval(rows: list[dict[str, Any]], contrast: str) -> list[float]:
    ids = sorted(row["task_id"] for row in rows)
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("expected one paired row per task cluster")
    by_id = {row["task_id"]: row for row in rows}
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = [statistics.mean(by_id[rng.choice(ids)][contrast] for _ in ids)
                 for _ in range(BOOTSTRAP_SAMPLES)]
    return [round(_percentile(estimates, 0.025), 4), round(_percentile(estimates, 0.975), 4)]


def analyze(data: dict[str, Any], *, expected_clusters: int = 30,
            study_shape: StudyShape | None = None) -> dict[str, Any]:
    task_families = data["encoding_pairs"]
    task_ids = sorted(task_families)
    if study_shape is not None:
        observed_pairs = [tuple(sorted(task_families[task_id])) for task_id in task_ids]
        pair_counts = Counter(observed_pairs)
        if (data.get("study") != study_shape.study
                or data.get("seed") != study_shape.seed
                or data.get("order_seed") != study_shape.order_seed
                or task_ids != list(study_shape.task_ids)
                or dict(pair_counts) != dict(study_shape.pair_counts)):
            raise ValueError("study identity, seed, or task families disagree with preregistration")
    if len(task_ids) != expected_clusters or data.get("repetitions_per_task") != 1:
        raise ValueError(f"expected {expected_clusters} new task clusters with one trial each")
    if data.get("arms") != list(ARMS):
        raise ValueError("unexpected diagnostic arms")
    records = data["records"]
    keys = [(row["case"], row["arm"]) for row in records]
    cases = sorted({row["case"] for row in records})
    expected = {(case, arm) for case in cases for arm in ARMS}
    if len(cases) != expected_clusters or len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("expected exactly one result per case and arm")
    by_key = {(row["case"], row["arm"]): row for row in records}
    comparisons = {row["case"]: row for row in data["comparisons"]}
    if set(comparisons) != set(cases):
        raise ValueError("comparison records do not match arm results")

    rows: list[dict[str, Any]] = []
    for case in cases:
        task_id = case.rsplit("-rep-", 1)[0]
        if task_id not in task_families or comparisons[case]["task_id"] != task_id:
            raise ValueError("unknown task cluster")
        outcomes: dict[str, bool] = {}
        protocols: dict[str, bool] = {}
        for arm in ARMS:
            record = by_key[(case, arm)]
            if record["task_id"] != task_id:
                raise ValueError("record task cluster does not match its case")
            expected_jobs = 1 if arm == "single" else 2
            protocol = (record["synthesis_complete"] is True
                        and len(record["job_states"]) == expected_jobs
                        and all(state == "completed" for state in record["job_states"]))
            outcomes[arm] = bool(protocol and record["oracle_verified"])
            protocols[arm] = bool(protocol)
            comparisons[case]["arms"][arm]["workflow_complete"] = bool(protocol)
            comparisons[case]["arms"][arm]["workflow_verified"] = outcomes[arm]
            cached = comparisons[case]["arms"][arm]
            for field in ("oracle_verified", "calls_observed", "calls_reserved", "elapsed_seconds"):
                if cached.get(field) != record.get(field):
                    raise ValueError("comparison arm metric disagrees with retained record")
        rows.append({"case": case, "task_id": task_id,
                     "primary_delta": int(outcomes["multi_combined"]) - int(outcomes["single"]),
                     "handoff_delta": int(outcomes["multi_combined"]) - int(outcomes["multi_separate"]),
                     "handoff_completion_delta": int(protocols["multi_combined"]) - int(protocols["multi_separate"]),
                     "handoff_oracle_delta": int(bool(by_key[(case, "multi_combined")]["oracle_verified"]))
                                              - int(bool(by_key[(case, "multi_separate")]["oracle_verified"])),
                     "single": outcomes["single"], "multi_separate": outcomes["multi_separate"],
                     "multi_combined": outcomes["multi_combined"], "protocols": protocols})

    per_arm: dict[str, Any] = {}
    for arm in ARMS:
        selected = [by_key[(case, arm)] for case in cases]
        usage_complete = all(row["usage_complete"] for row in selected)
        per_arm[arm] = {
            "trials": len(selected),
            "oracle_verified": sum(bool(row["oracle_verified"]) for row in selected),
            "workflow_complete": sum(bool(row["protocols"][arm]) for row in rows),
            "workflow_complete_oracle_verified": sum(bool(row[arm]) for row in rows),
            "mean_elapsed_seconds": round(statistics.mean(row["elapsed_seconds"] for row in selected), 3),
            "mean_calls_observed": round(statistics.mean(row["calls_observed"] for row in selected), 3),
            "mean_calls_reserved": round(statistics.mean(row["calls_reserved"] for row in selected), 3),
            "mean_actions": round(statistics.mean(row["actions"] for row in selected), 3),
            "candidate_ready_jobs_at_termination": sum(row["candidate_ready_jobs"] for row in selected),
            "decision_counts": dict(sum((Counter(row["decision_counts"]) for row in selected), Counter())),
            "report_rejections": sum(row["report_rejections"] for row in selected),
            "report_rejection_categories": dict(sum(
                (Counter(row["report_rejection_categories"]) for row in selected), Counter())),
            "report_rejection_stages": dict(sum(
                (Counter(row.get("report_rejection_stages", {})) for row in selected), Counter())),
            "terminal_reason_categories": dict(sum(
                (Counter(row["terminal_reason_categories"]) for row in selected), Counter())),
            "model_turn_budget_denials": sum(row["model_turn_budget_denials"] for row in selected),
            "candidate_ready_call_ceiling_failures": sum(
                row["candidate_ready_jobs"] > 0 and not comparisons[row["case"]]["arms"][arm]["workflow_complete"]
                and row["calls_reserved"] >= 8 for row in selected),
            "token_usage_complete": usage_complete,
            "mean_input_tokens": (round(statistics.mean(row["usage"]["input_tokens"] for row in selected), 1)
                                  if usage_complete else "unknown"),
            "mean_output_tokens": (round(statistics.mean(row["usage"]["output_tokens"] for row in selected), 1)
                                   if usage_complete else "unknown"),
            "cost_usd": "unknown",
        }
    primary = statistics.mean(row["primary_delta"] for row in rows)
    handoff = statistics.mean(row["handoff_delta"] for row in rows)
    handoff_completion = statistics.mean(row["handoff_completion_delta"] for row in rows)
    handoff_oracle = statistics.mean(row["handoff_oracle_delta"] for row in rows)
    primary_ci = _cluster_interval(rows, "primary_delta")
    handoff_ci = _cluster_interval(rows, "handoff_delta")
    discordance = {}
    for left, right, name in (("multi_combined", "single", "combined_vs_single"),
                              ("multi_combined", "multi_separate", "combined_vs_separate")):
        discordance[name] = {
            "both": sum(row[left] and row[right] for row in rows),
            "left_only": sum(row[left] and not row[right] for row in rows),
            "right_only": sum(not row[left] and row[right] for row in rows),
            "neither": sum(not row[left] and not row[right] for row in rows),
        }
    return {
        "study": data["study"], "model": data["model"], "cli": data["cli"],
        "distinct_task_clusters": len(task_ids), "arms": per_arm,
        "primary_contrast_multi_combined_minus_single": round(primary, 4),
        "primary_cluster_bootstrap_95_interval": primary_ci,
        "primary_gain_gate_met": primary_ci[0] > 0,
        "mechanism_contrast_multi_combined_minus_multi_separate": round(handoff, 4),
        "mechanism_cluster_bootstrap_95_interval": handoff_ci,
        "handoff_completion_contrast_multi_combined_minus_multi_separate": round(handoff_completion, 4),
        "handoff_completion_cluster_bootstrap_95_interval": _cluster_interval(rows, "handoff_completion_delta"),
        "handoff_oracle_correctness_contrast_multi_combined_minus_multi_separate": round(handoff_oracle, 4),
        "handoff_oracle_correctness_cluster_bootstrap_95_interval": _cluster_interval(rows, "handoff_oracle_delta"),
        "discordant_pairs": discordance,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED,
                      "resampling_unit": "task_id"},
        "limitations": [
            "One trial per synthetic task cluster; the cluster bootstrap reflects task sampling, not within-task repetition.",
            "The combined-handoff contrast includes its report-timing and retry behavior, not only the saved call.",
            "A positive handoff mechanism contrast does not alone prove the historical call-starvation hypothesis.",
            "Synthetic encoding tasks do not establish general CTF or AlpacaHack performance.",
            "Provider cost is unknown.",
        ],
    }


def main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        shape = PILOT_SHAPE if data.get("study") == PILOT_SHAPE.study else None
        result = analyze(data, expected_clusters=len(shape.task_ids) if shape else 30,
                         study_shape=shape)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
