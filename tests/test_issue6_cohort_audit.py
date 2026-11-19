import json
import sys
from itertools import product

import pytest
from pydantic import ValidationError

from metis.evaluation.issue6_cohort_audit import MAX_INPUT_BYTES, audit
from metis.evaluation.issue6_cohort_audit import main as audit_main
from metis.evaluation.issue6_heldout_comparison import (
    ARMS,
    FAMILIES,
    OutcomeExport,
    Registration,
    Resources,
    Task,
    Trial,
)
from metis.evaluation.issue6_heldout_comparison import (
    analyze as analyze_outcomes,
)


@pytest.fixture
def cohort():
    cap = Resources(calls=10, input_tokens=1000, generated_tokens=300, actions=10, wall_ms=1000)
    tasks = [Task(id=f"case-{index:03d}", family=FAMILIES[index // 20]) for index in range(60)]
    registration = Registration(commitment="a" * 64, tasks=tasks, cap=cap)
    records = []
    for task, arm in product(tasks, ARMS):
        succeeded = arm == "complementary" and int(task.id[-3:]) < 30
        records.append(
            Trial(
                task=task.id,
                arm=arm,
                outcome="complete",
                oracle_verified=succeeded,
                usage=Resources(
                    calls=8, input_tokens=800, generated_tokens=200, actions=8, wall_ms=900
                ),
            )
        )
    return registration, OutcomeExport(commitment=registration.commitment, records=records)


def test_complete_packet_reuses_existing_score_without_qualifying_execution(cohort):
    registration, outcomes = cohort
    result = audit(registration, outcomes)
    assert result["status"] == "consistency_only"
    assert result["unverified_score_projection"] == analyze_outcomes(registration, outcomes)
    assert result["scorer_fixed_arms"] == list(ARMS)
    assert result["order_check"] == "canonical_serialization_only"
    assert result["evidence_reference_count"] == 0
    assert result["execution_evidence_status"] == "unavailable_not_checked"
    assert result["execution_order_status"] == "unavailable_preregistered_order_not_in_schema"
    assert (
        result["oracle_verification_status"] == "declared_outcomes_only_not_independently_verified"
    )
    assert result["unavailable_evidence"]["execution_receipts"].startswith("not present")
    assert result["unverified_score_projection"]["bundle_thresholds_met"]


def test_missing_trial_is_ineligible_not_a_complete_cohort(cohort):
    registration, outcomes = cohort
    outcomes.records.pop()
    result = audit(registration, outcomes)
    assert result["status"] == "ineligible"
    assert result["execution_order_status"] == "unavailable_preregistered_order_not_in_schema"
    assert result["unverified_score_projection"]["status"] == "ineligible"
    assert result["unverified_score_projection"]["missing_records"] == 1


def test_duplicate_or_unregistered_trial_fails_closed(cohort):
    registration, outcomes = cohort
    outcomes.records[-1] = outcomes.records[0]
    with pytest.raises(ValueError, match="duplicate or unregistered"):
        audit(registration, outcomes)


def test_reordered_export_is_rejected(cohort):
    registration, outcomes = cohort
    outcomes.records[0], outcomes.records[1] = outcomes.records[1], outcomes.records[0]
    with pytest.raises(ValueError, match="canonical registration-task"):
        audit(registration, outcomes)


def test_mismatched_commitment_and_over_cap_usage_are_not_scored(cohort):
    registration, outcomes = cohort
    outcomes.commitment = "b" * 64
    with pytest.raises(ValueError, match="commitment disagrees"):
        audit(registration, outcomes)

    outcomes.commitment = registration.commitment
    outcomes.records[0].usage = outcomes.records[0].usage.model_copy(update={"wall_ms": 1001})
    result = audit(registration, outcomes)
    assert result["status"] == "ineligible"
    assert result["unverified_score_projection"]["over_cap"] == 1


def test_answer_or_unmodeled_receipt_fields_are_rejected(cohort):
    _, outcomes = cohort
    row = outcomes.records[0].model_dump()
    with pytest.raises(ValidationError):
        Trial.model_validate({**row, "candidate": "private"})
    with pytest.raises(ValidationError):
        Trial.model_validate({**row, "execution_receipt": {"runtime_sha256": "a" * 64}})


def test_boolean_usage_counter_is_not_an_integer_measurement(cohort):
    registration, outcomes = cohort
    row = outcomes.records[0].model_dump()
    with pytest.raises(ValidationError):
        Trial.model_validate({**row, "usage": {**row["usage"], "calls": True}})

    outcomes.records[0].usage.calls = True
    with pytest.raises(ValidationError):
        audit(registration, outcomes)


def test_cli_suppresses_private_input_and_path_details(cohort, tmp_path, monkeypatch, capsys):
    registration, outcomes = cohort
    registration_path = tmp_path / "registration.json"
    outcomes_path = tmp_path / "outcomes.json"
    registration_path.write_text(registration.model_dump_json(), encoding="utf-8")
    secret = "private-answer-sentinel-7d3a"
    private_payload = outcomes.model_dump()
    private_payload["unexpected_private_field"] = secret
    outcomes_path.write_text(json.dumps(private_payload), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["issue6-cohort-audit", str(registration_path), str(outcomes_path)]
    )
    with pytest.raises(SystemExit) as raised:
        audit_main()
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert secret not in captured.out + captured.err

    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_bytes(secret.encode() + b" " * MAX_INPUT_BYTES)
    monkeypatch.setattr(
        sys, "argv", ["issue6-cohort-audit", str(registration_path), str(oversized_path)]
    )
    with pytest.raises(SystemExit) as raised:
        audit_main()
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert secret not in captured.out + captured.err

    private_path = tmp_path / f"missing-{secret}.json"
    monkeypatch.setattr(sys, "argv", ["issue6-cohort-audit", str(private_path), str(outcomes_path)])
    with pytest.raises(SystemExit) as raised:
        audit_main()
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert secret not in captured.out + captured.err
