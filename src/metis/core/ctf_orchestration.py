"""Bounded planner/executor wave specifications for AI subagents.

This module emits plans only; the selected AI remains the agent runtime and the
official verifier remains controller-owned.
"""
from __future__ import annotations

from typing import Any

CATEGORY_OBJECTIVES = {
    "crypto": "Identify the primitive and test the cheapest discriminating decode or attack.",
    "web": "Map supplied application evidence and propose one scoped, verifiable web hypothesis.",
    "pwn": "Determine mitigations, input boundary, and a plausible exploitation primitive statically.",
    "rev": "Recover control flow, constants, and the candidate validation transformation statically.",
    "forensics": "Identify containers and metadata, then test the most likely hidden-data layer.",
    "misc": "Classify the representation and reduce it to a more specific, testable problem.",
}


def plan_agent_wave(context: dict[str, Any]) -> dict[str, Any]:
    """Return two to four distinct, minimal-context assignments for one solve wave."""
    challenge = context.get("challenge", {})
    categories = [str(item) for item in challenge.get("categories", [])]
    artifacts = [str(item) for item in challenge.get("artifacts", [])]
    assignments: list[dict[str, Any]] = []
    if artifacts:
        assignments.append({
            "role": "artifact-triage",
            "objective": "Classify declared artifacts and return the highest-value next parser or transform.",
            "inputs": {"artifacts": artifacts[:32]},
            "deliverable": "Observed formats, concrete evidence, and one ranked next action.",
            "max_turns": 4,
        })
    for category in categories[:2] or ["misc"]:
        assignments.append({
            "role": f"{category}-specialist",
            "objective": CATEGORY_OBJECTIVES.get(category, CATEGORY_OBJECTIVES["misc"]),
            "inputs": {"run_id": context.get("run_id"), "category": category},
            "deliverable": "Hypothesis, supporting observation, falsifier, and one next tool action.",
            "max_turns": 6,
        })
    assignments.append({
        "role": "independent-critic",
        "objective": "Challenge the leading hypothesis and check that a candidate is not mistaken for proof.",
        "inputs": {"run_id": context.get("run_id")},
        "deliverable": "One material risk or contradiction, plus verification required to resolve it.",
        "max_turns": 4,
    })
    unique: list[dict[str, Any]] = []
    roles: set[str] = set()
    for assignment in assignments:
        if assignment["role"] not in roles:
            roles.add(assignment["role"])
            unique.append(assignment)
    unique = unique[:4]
    for assignment in unique:
        assignment.update({
            "model_policy": "smallest-capable-lower-tier",
            "context_policy": "no-history; provide only referenced evidence",
            "may_submit": False,
            "may_expand_scope": False,
        })
    return {
        "run_id": context.get("run_id"),
        "architecture": "planner-fresh-executors-compact-summaries",
        "assignments": unique,
        "synthesis_gate": {
            "required_fields": ["hypothesis", "evidence", "next_action"],
            "reject": ["duplicate_action", "unsupported_candidate", "scope_expansion"],
            "official_submission_owner": "Daybreak",
        },
        "next_wave_rule": "Start another wave only for unresolved, materially different hypotheses.",
    }
