"""Consistency-only audit for the current Issue #6 paired outcome export.

This layer deliberately consumes the existing Registration and OutcomeExport
schemas. Those schemas do not contain per-run receipts, runtime/configuration
digests, deadlines, or a preregistered execution order. A complete packet can
therefore be checked for internal consistency and scored by the existing
analyzer, but cannot qualify execution provenance or the Issue #6 gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .issue6_heldout_comparison import ARMS, OutcomeExport, Registration
from .issue6_heldout_comparison import analyze as analyze_outcomes

MAX_INPUT_BYTES = 1024 * 1024

UNAVAILABLE_EVIDENCE = {
    "execution_receipts": "not present in Registration or OutcomeExport",
    "source_provenance": "not authenticated by the current packet schema",
    "runtime_configuration": "not present in the current packet schema",
    "actual_budget_enforcement": "reported usage can be compared with the registered cap only",
    "deadlines": "per-trial start, finish, and deadline values are not present",
    "preregistered_execution_order": "not present; only canonical export serialization order is checked",
}


def audit(registration: Registration, outcomes: OutcomeExport) -> dict[str, object]:
    """Validate packet consistency and retain the existing scorer's projection.

    The output status is always ``consistency_only`` for a complete eligible
    packet. Ineligible packets are returned before the ordering check.
    Malformed, duplicate, or unregistered records fail closed through the
    existing scorer; a complete eligible packet with non-canonical export
    ordering fails closed with ``ValueError``.
    """
    # Revalidate model instances too: Pydantic models are mutable, and the
    # upstream scoring contracts do not enable assignment validation.
    registration = Registration.model_validate(registration.model_dump())
    outcomes = OutcomeExport.model_validate(outcomes.model_dump())
    score = analyze_outcomes(registration, outcomes)
    if score["status"] != "scored":
        return {
            "status": "ineligible",
            "consistency": "incomplete_or_invalid",
            "execution_order_status": "unavailable_preregistered_order_not_in_schema",
            "execution_evidence_status": "unavailable_not_checked",
            "evidence_reference_count": 0,
            "score_projection_basis": "caller_supplied OutcomeExport values",
            "oracle_verification_status": "declared_outcomes_only_not_independently_verified",
            "unverified_score_projection": score,
            "unavailable_evidence": UNAVAILABLE_EVIDENCE.copy(),
        }

    expected_order = [(task.id, arm) for task in registration.tasks for arm in ARMS]
    observed_order = [(record.task, record.arm) for record in outcomes.records]
    if observed_order != expected_order:
        raise ValueError(
            "outcome records are not in canonical registration-task and arm serialization order"
        )

    return {
        "status": "consistency_only",
        "consistency": "valid",
        "order_check": "canonical_serialization_only",
        "registered_tasks": len(registration.tasks),
        "scorer_fixed_arms": list(ARMS),
        "outcome_records": len(outcomes.records),
        "reported_usage_within_registered_caps": True,
        "execution_order_status": "unavailable_preregistered_order_not_in_schema",
        "execution_evidence_status": "unavailable_not_checked",
        "evidence_reference_count": 0,
        "score_projection_basis": "caller_supplied OutcomeExport values",
        "oracle_verification_status": "declared_outcomes_only_not_independently_verified",
        "unverified_score_projection": score,
        "unavailable_evidence": UNAVAILABLE_EVIDENCE.copy(),
        "limitations": [
            "This output does not establish that the supplied registration was frozen before execution.",
            "This output does not authenticate source artifacts, runtime settings, or execution receipts.",
            "This output does not verify deadline enforcement or provider-side resource limits.",
            "The score projection is not verified benchmark evidence and does not establish measured gain.",
        ],
    }


def _read_bounded(path: Path) -> bytes:
    """Read one CLI input with a fixed cap before parsing or retaining it."""
    with path.open("rb") as source:
        payload = source.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("cohort input exceeds the size limit")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration", type=Path)
    parser.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    try:
        registration = Registration.model_validate_json(_read_bounded(args.registration))
        outcomes = OutcomeExport.model_validate_json(_read_bounded(args.outcomes))
        result = audit(registration, outcomes)
    except (OSError, ValueError):
        parser.exit(2, "Issue #6 cohort consistency audit failed; input details were suppressed.\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
