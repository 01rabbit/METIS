from itertools import product

import pytest
from pydantic import ValidationError

from metis.evaluation.issue6_heldout_comparison import (
    ARMS,
    FAMILIES,
    OutcomeExport,
    Registration,
    Resources,
    Task,
    Trial,
    analyze,
)


@pytest.fixture
def paired_study() -> tuple[Registration, OutcomeExport]:
    cap = Resources(calls=10, input_tokens=1000, generated_tokens=300, actions=10, wall_ms=1000)
    tasks = [Task(id=f"case-{i:03d}", family=FAMILIES[i // 20]) for i in range(60)]
    registration = Registration(commitment="a" * 64, tasks=tasks, cap=cap)
    records = [
        Trial(task=task.id, arm=arm, outcome="complete", oracle_verified=False, usage=cap)
        for task, arm in product(tasks, ARMS)
    ]
    return registration, OutcomeExport(commitment=registration.commitment, records=records)


def test_both_controls_must_be_beaten(paired_study):
    registration, outcomes = paired_study
    for row in outcomes.records[:18]:
        row.oracle_verified = row.arm != "single"
    result = analyze(registration, outcomes)
    assert not result["bundle_thresholds_met"]
    assert result["contrasts"]["single"]["one_sided_exact_p"] == 1 / 64
    for row in outcomes.records[:18]:
        row.oracle_verified = row.arm == "complementary"
    assert analyze(registration, outcomes)["bundle_thresholds_met"]


def test_ineligible_is_not_scored(paired_study):
    registration, outcomes = paired_study
    outcomes.records.pop()
    outcomes.records[0].usage = None
    outcomes.records[1].usage = registration.cap.model_copy(update={"generated_tokens": 301})
    outcomes.records[2].outcome = "infrastructure_failure"
    outcomes.records[2].oracle_verified = None
    assert analyze(registration, outcomes) == {
        "status": "ineligible",
        "missing_records": 1,
        "infrastructure_failures": 1,
        "missing_usage": 1,
        "over_cap": 1,
    }


def test_rejects_unregistered_or_duplicate_records(paired_study):
    registration, outcomes = paired_study
    outcomes.records[-1] = outcomes.records[0]
    with pytest.raises(ValueError, match="duplicate or unregistered"):
        analyze(registration, outcomes)
    outcomes.records[-1] = outcomes.records[0].model_copy(update={"task": "case-999"})
    with pytest.raises(ValueError, match="duplicate or unregistered"):
        analyze(registration, outcomes)


def test_export_rejects_candidate_and_nonboolean_verdict(paired_study):
    _, outcomes = paired_study
    row = outcomes.records[0].model_dump()
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Trial.model_validate({**row, "candidate": "private"})
    with pytest.raises(ValidationError, match="bool_type"):
        Trial.model_validate({**row, "oracle_verified": 1})


def test_missing_complete_verdict_and_commitment_mismatch(paired_study):
    registration, outcomes = paired_study
    outcomes.records[0].oracle_verified = None
    with pytest.raises(ValueError, match="complete workflow has an oracle verdict"):
        analyze(registration, outcomes)
    outcomes.commitment = "b" * 64
    with pytest.raises(ValueError, match="commitment disagrees"):
        analyze(registration, outcomes)
