"""Deterministic, answer-free diagnosis of the frozen Issue #6 replication.

Only retained arm metrics are used. Missing event-level evidence is never
reconstructed from a call count or a failed job state.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def diagnose(data: dict[str, Any]) -> dict[str, Any]:
    records = data["records"]
    cases = {pair["case"] for pair in data["pairs"]}
    keys = [(record["case"], record["arm"]) for record in records]
    expected = {(case, arm) for case in cases for arm in ("single", "multi")}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("expected one record per case and arm")
    if len(cases) != 60 or len(data["encoding_pairs"]) != 30:
        raise ValueError("unexpected frozen replication shape")
    if any(set(record) & {"candidate", "component", "answer", "flag"} for record in records):
        raise ValueError("answer-bearing fields are outside the retained schema")

    arms: dict[str, Any] = {}
    for arm in ("single", "multi"):
        selected = [record for record in records if record["arm"] == arm]
        expected_jobs = 1 if arm == "single" else 2
        if any(len(record["job_states"]) != expected_jobs for record in selected):
            raise ValueError("unexpected job count")
        complete = [record for record in selected if record["synthesis_complete"] is True
                    and all(state == "completed" for state in record["job_states"])]
        incomplete = [record for record in selected if record not in complete]
        patterns = Counter(tuple(sorted(record["job_states"])) for record in selected)
        arms[arm] = {
            "trials": len(selected),
            "oracle_verified_any_workflow": sum(record["oracle_verified"] is True for record in selected),
            "report_complete": len(complete),
            "report_incomplete": len(incomplete),
            "report_complete_oracle_verified": sum(record["oracle_verified"] is True for record in complete),
            "oracle_verified_report_incomplete": sum(record["oracle_verified"] is True for record in incomplete),
            "report_complete_oracle_incorrect": sum(record["oracle_verified"] is False for record in complete),
            "job_state_patterns": {",".join(pattern): count for pattern, count in sorted(patterns.items())},
            "call_ceiling_reached": sum(record["calls_reserved"] >= 8 for record in selected),
            "incomplete_at_call_ceiling": sum(record["calls_reserved"] >= 8 for record in incomplete),
            "handoff_failure_observed": "unknown",
            "budget_denial_observed": "unknown",
        }
    return {
        "study": data["study"],
        "source": "frozen answer-free retained arm records",
        "arms": arms,
        "limits": [
            "An oracle-verified incomplete workflow is not a protocol-complete solve.",
            "Failed jobs and exhausted reservations do not identify candidate/report handoff failures.",
            "The retained records contain no budget-denial events or candidate-ready state.",
        ],
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        result = diagnose(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
