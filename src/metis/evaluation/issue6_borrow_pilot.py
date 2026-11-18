"""Validate and summarize the preregistered answer-free borrowing pilot."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from metis.evaluation.issue6_handoff_diagnostic import StudyShape
from metis.evaluation.issue6_handoff_diagnostic import analyze as analyze_paired

STUDY = "issue6-borrow-pilot-2026-11-18"
SEED = 2026111807
ARMS = ("single", "multi_fixed", "multi_borrow")
CANONICAL = {"single": "single", "multi_fixed": "multi_separate",
             "multi_borrow": "multi_combined"}
SHAPE = StudyShape(
    study=STUDY, seed=SEED, order_seed=SEED ^ 0x6A09E667,
    task_ids=tuple(f"borrow6-{index:02d}" for index in range(6)),
    pair_counts=((('base32', 'base64'), 2), (('base64', 'hex'), 2),
                 (('base64', 'base85'), 2)),
)


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    """Return paired outcomes; never inspect candidate or oracle contents."""
    if data.get("arms") != list(ARMS) or len(data.get("records", [])) != 18:
        raise ValueError("borrow pilot requires exactly 18 records in three frozen arms")
    transformed = copy.deepcopy(data)
    transformed["arms"] = list(CANONICAL.values())
    for record in transformed["records"]:
        record["arm"] = CANONICAL[record["arm"]]
    for comparison in transformed["comparisons"]:
        comparison["arms"] = {CANONICAL[arm]: row for arm, row in comparison["arms"].items()}
    summary = analyze_paired(transformed, expected_clusters=6, study_shape=SHAPE)
    return {
        "study": STUDY,
        "arms": {arm: summary["arms"][CANONICAL[arm]] for arm in ARMS},
        "borrow_minus_single": summary["primary_contrast_multi_combined_minus_single"],
        "borrow_minus_single_cluster_bootstrap_95_interval": summary["primary_cluster_bootstrap_95_interval"],
        "borrow_minus_fixed": summary["mechanism_contrast_multi_combined_minus_multi_separate"],
        "borrow_minus_fixed_cluster_bootstrap_95_interval": summary["mechanism_cluster_bootstrap_95_interval"],
        "discordant_pairs": summary["discordant_pairs"],
        "primary_gain_gate_met": False,  # Six synthetic clusters never close P5.
        "pilot_positive": summary["primary_contrast_multi_combined_minus_single"] > 0,
        "bootstrap": summary["bootstrap"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(analyze(data), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
