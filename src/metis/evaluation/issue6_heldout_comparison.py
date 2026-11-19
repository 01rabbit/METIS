"""Score a complete, redacted Issue #6 paired outcome export offline."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Arm = Literal["single", "best_of_two", "complementary"]
Family = Literal["log_records", "byte_records", "scheduling"]
Outcome = Literal["complete", "exhausted", "invalid_output", "infrastructure_failure"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TaskID = Annotated[str, Field(pattern=r"^case-[0-9]{3}$")]
Count = Annotated[int, Field(ge=0)]
ARMS: tuple[Arm, ...] = ("single", "best_of_two", "complementary")
FAMILIES: tuple[Family, ...] = ("log_records", "byte_records", "scheduling")


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Resources(StrictRecord):
    calls: Count
    input_tokens: Count
    generated_tokens: Count
    actions: Count
    wall_ms: Count

    def exceeds(self, cap: Resources) -> bool:
        limits = cap.model_dump()
        return any(value > limits[name] for name, value in self.model_dump().items())


class Task(StrictRecord):
    id: TaskID
    family: Family


class Registration(StrictRecord):
    commitment: Digest
    tasks: Annotated[list[Task], Field(min_length=60, max_length=60)]
    cap: Resources


class Trial(StrictRecord):
    task: TaskID
    arm: Arm
    outcome: Outcome
    oracle_verified: bool | None
    usage: Resources | None


class OutcomeExport(StrictRecord):
    commitment: Digest
    records: Annotated[list[Trial], Field(max_length=180)]


def _compare(candidate: list[bool], control: list[bool]) -> dict[str, int | float | bool]:
    gains = sum(result and not baseline for result, baseline in zip(candidate, control, strict=True))
    losses = sum(baseline and not result for result, baseline in zip(candidate, control, strict=True))
    discordant = gains + losses
    p_value = Fraction(sum(comb(discordant, k) for k in range(gains, discordant + 1)), 2**discordant)
    rate_delta = Fraction(gains - losses, len(candidate))
    return {
        "candidate_only": gains,
        "control_only": losses,
        "difference_percentage_points": float(100 * rate_delta),
        "one_sided_exact_p": float(p_value),
        "passes": rate_delta >= Fraction(1, 10) and p_value <= Fraction(1, 40),
    }


def analyze(registration: Registration, outcomes: OutcomeExport) -> dict[str, object]:
    """Validate pairing and score the registered endpoint; execution remains independently auditable."""
    task_ids = {task.id for task in registration.tasks}
    if len(task_ids) != 60 or Counter(t.family for t in registration.tasks) != dict.fromkeys(FAMILIES, 20):
        raise ValueError("registration requires 60 unique tasks, 20 per family")
    if not all(registration.cap.model_dump().values()):
        raise ValueError("all registered caps must be positive")
    if outcomes.commitment != registration.commitment:
        raise ValueError("outcome commitment disagrees with registration")
    expected = {(task_id, arm) for task_id in task_ids for arm in ARMS}
    rows = {(row.task, row.arm): row for row in outcomes.records}
    if len(rows) != len(outcomes.records) or not rows.keys() <= expected:
        raise ValueError("duplicate or unregistered trial records")

    missing = expected - rows.keys()
    infrastructure_failures = 0
    missing_usage = 0
    over_cap = 0
    for row in rows.values():
        if (row.outcome == "complete") != (row.oracle_verified is not None):
            raise ValueError("only a complete workflow has an oracle verdict")
        infrastructure_failures += row.outcome == "infrastructure_failure"
        missing_usage += row.usage is None
        over_cap += row.usage is not None and row.usage.exceeds(registration.cap)
    invalid_counts = {
        "missing_records": len(missing),
        "infrastructure_failures": infrastructure_failures,
        "missing_usage": missing_usage,
        "over_cap": over_cap,
    }
    if any(invalid_counts.values()):
        return {"status": "ineligible", **invalid_counts}

    success = {
        arm: [rows[(task_id, arm)].oracle_verified is True for task_id in sorted(task_ids)]
        for arm in ARMS
    }
    contrasts = {
        control: _compare(success["complementary"], success[control])
        for control in ("best_of_two", "single")
    }
    return {
        "status": "scored",
        "workflow_successes": {arm: sum(values) for arm, values in success.items()},
        "contrasts": contrasts,
        "bundle_thresholds_met": all(contrast["passes"] for contrast in contrasts.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration", type=Path)
    parser.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    registration = Registration.model_validate_json(args.registration.read_bytes())
    outcomes = OutcomeExport.model_validate_json(args.outcomes.read_bytes())
    print(json.dumps(analyze(registration, outcomes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
