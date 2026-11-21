"""Typed contracts and pure policy for Daybreak specialist orchestration (Issue #11, P1).

Everything here is deterministic and side-effect free: no model calls, no database.
See docs/CTF_ENVIRONMENT_AND_ORCHESTRATION.md sections 4-6 and 9.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.core.ctf_triage import PLAYBOOKS

SCHEMA_VERSION = 2
CATEGORIES = ("crypto", "web", "forensics", "rev", "pwn", "misc")
ExecutionMode = Literal["sequential", "delegated"]
JobState = Literal["queued", "running", "completed", "failed", "cancelled", "timed_out", "unknown"]
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled", "timed_out"}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    @field_validator("*", mode="after")
    @classmethod
    def _finite(cls, value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number")
        return value


class SpecialistProfile(Contract):
    schema_version: int = SCHEMA_VERSION
    role: str = Field(min_length=3, max_length=40)
    category: str | None = None
    objective: str = Field(min_length=10, max_length=400)
    recommended_tools: list[str] = Field(default_factory=list, max_length=24)
    evidence_required: str = Field(min_length=10, max_length=400)
    deliverable: str = Field(min_length=10, max_length=400)
    max_turns: int = Field(ge=1, le=20)
    tier: Literal["lower", "standard", "strong"] = "standard"
    may_submit: Literal[False] = False
    may_expand_scope: Literal[False] = False
    may_handle_credentials: Literal[False] = False
    may_delegate: Literal[False] = False


class Assignment(Contract):
    schema_version: int = SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=64)
    wave_id: str = Field(min_length=1, max_length=64)
    assignment_id: str = Field(min_length=1, max_length=80)
    profile: SpecialistProfile
    scope_refs: list[str] = Field(default_factory=list, max_length=32)
    artifact_refs: list[str] = Field(default_factory=list, max_length=32)
    evidence_refs: list[int] = Field(default_factory=list, max_length=20)
    deadline_seconds: int = Field(ge=30, le=4 * 3600)
    max_output_chars: int = Field(default=8000, ge=500, le=20000)
    permissions: dict[str, bool] = Field(default_factory=lambda: {
        "submit": False, "expand_scope": False, "credentials": False, "delegate": False})


class ModelSelection(Contract):
    requested_tier: Literal["lower", "standard", "strong"]
    model: str | None = Field(default=None, max_length=120)  # None = reuse the host's current model
    source: Literal["catalog", "current"]
    reason: str = Field(min_length=3, max_length=300)
    fallback_reason: str | None = Field(default=None, max_length=300)
    escalated: bool = False
    usage_known: bool = False


class ExecutionRecord(Contract):
    assignment_id: str
    attempt_id: str
    host: str
    host_job_id: str | None = None
    state: JobState
    lease_until: float | None = None
    started: float | None = None
    finished: float | None = None
    failure: str | None = Field(default=None, max_length=300)
    turns_used: int = Field(default=0, ge=0)
    usage: dict[str, Any] = Field(default_factory=lambda: {"tokens": "unknown", "cost": "unknown"})


class CompactReport(Contract):
    """The six existing report fields plus optional, checkable references."""

    schema_version: int = SCHEMA_VERSION
    hypothesis: str = Field(min_length=5, max_length=2000)
    evidence: str = Field(min_length=5, max_length=2000)
    falsifier: str = Field(min_length=5, max_length=2000)
    next_action: str = Field(min_length=5, max_length=2000)
    event_sequences: list[int] = Field(min_length=1, max_length=20)
    status: Literal["supported", "rejected", "inconclusive"] = "inconclusive"
    artifact_refs: list[str] = Field(default_factory=list, max_length=16)
    next_action_intent: dict[str, Any] | None = None
    action_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_sequences")
    @classmethod
    def _non_negative(cls, value: list[int]) -> list[int]:
        if any(item < 0 for item in value):
            raise ValueError("event sequences are non-negative")
        return value


class ProposedAction(Contract):
    """A future tool request declaration used only for repeat-strategy comparison."""

    kind: Literal["data", "artifact", "derive", "view"]
    tool: str = Field(min_length=1, max_length=40)
    data: str | None = Field(default=None, max_length=65_536)
    artifact: str | None = Field(default=None, max_length=200)
    options: dict[str, Any] = Field(default_factory=dict)
    new_evidence: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _request_shape(self) -> ProposedAction:
        if self.kind == "data" and (self.data is None or self.artifact is not None or self.options):
            raise ValueError("data proposals require data and cannot include artifact options")
        if self.kind in {"artifact", "derive"} and (self.artifact is None or self.data is not None):
            raise ValueError("artifact proposals require an artifact and cannot include data")
        if self.kind == "view" and (self.tool != "view" or self.artifact is None or self.data is not None
                                    or self.options):
            raise ValueError("view proposals require tool=view and an artifact only")
        return self


class WaveDecision(Contract):
    schema_version: int = SCHEMA_VERSION
    execution_mode: ExecutionMode
    required_roles: list[str] = Field(default_factory=list, max_length=4)
    daybreak_covers: list[str] = Field(default_factory=list, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=2)
    category_source: Literal["declared", "triage", "default"]
    category_reason: str = Field(max_length=300)
    reason: str = Field(max_length=300)


# -- profiles -------------------------------------------------------------------------------
_EVIDENCE = {
    "crypto": "Encoding vs cipher, keys/modulus/exponent, known conditions and data length.",
    "web": "Supplied source, HTTP messages, auth boundary, cookie/JWT and the input-to-output path.",
    "forensics": "Real magic, digest, size, container, metadata and capture/image/audio structure.",
    "rev": "Format and ISA, sections, symbols, constants and the input check's control flow.",
    "pwn": "ISA, imports, mitigation indicators, input boundary and known offsets.",
    "misc": "Representation, file type and statement constraints; possible reclassification.",
}
_OBJECTIVE = {
    "crypto": "Identify the primitive and test the cheapest discriminating decode or attack.",
    "web": "Map supplied application evidence and propose one scoped, verifiable web hypothesis.",
    "pwn": "Determine mitigations, input boundary, and a plausible exploitation primitive.",
    "rev": "Recover control flow, constants, and the candidate validation transformation.",
    "forensics": ("Identify containers and metadata, then test the most likely hidden-data layer; for logs and "
                  "incident evidence, read records with the bounded evidence readers and cite record locations."),
    "misc": "Classify the representation and reduce it to a more specific, testable problem.",
}

PROFILES: dict[str, SpecialistProfile] = {
    f"{category}-specialist": SpecialistProfile(
        role=f"{category}-specialist", category=category, objective=_OBJECTIVE[category],
        recommended_tools=list(PLAYBOOKS[category]["tools"])[:24], evidence_required=_EVIDENCE[category],
        deliverable="Hypothesis, supporting observation, falsifier, and one next tool action.",
        max_turns=6, tier="standard")
    for category in CATEGORIES
}
PROFILES["artifact-triage"] = SpecialistProfile(
    role="artifact-triage", objective="Classify declared artifacts and return the highest-value next parser.",
    recommended_tools=["overview", "strings", "hex", "zip_list", "tar_list", "elf", "pe", "image", "pcap"],
    evidence_required="File magic, size, structure and which bounded parser applies.",
    deliverable="Observed formats, concrete evidence, and one ranked next action.", max_turns=4, tier="lower")
PROFILES["independent-critic"] = SpecialistProfile(
    role="independent-critic", objective="Challenge the leading hypothesis; keep candidates from being taken as proof.",
    recommended_tools=[], evidence_required="The leading hypothesis and the observations it relies on.",
    deliverable="One material risk or contradiction, plus verification required to resolve it.",
    max_turns=4, tier="lower")

# Native data/artifact tools a specialist may ask the controller to run (via intents).
# Everything that submits, authenticates, grants scope or reaches the network is absent.
INTENT_KINDS = {"data", "artifact", "derive"}


CategorySource = Literal["declared", "triage", "default"]


def _categories(context: dict[str, Any]) -> tuple[list[str], CategorySource, str]:
    challenge = context.get("challenge", {})
    declared = [str(item) for item in challenge.get("categories", []) if str(item) in CATEGORIES]
    if declared:
        return declared[:2], "declared", "categories declared in the manifest"
    suggested = [item for item in context.get("triage", {}).get("suggested_categories", [])
                 if item in CATEGORIES and item != "misc"]
    if suggested:
        return suggested[:2], "triage", "triage from artifact magic and title/description/artifact-name keywords (unverified)"
    return ["misc"], "default", "no declared or suggested category"


def decide_wave(context: dict[str, Any], *, force_mode: ExecutionMode | None = None) -> WaveDecision:
    """Sequential unless there is independent useful work for more than one specialist.

    Delegated when two categories are in play, or when there are several artifacts to
    classify alongside a category. A single category with at most one artifact is a
    "simple" problem: Daybreak covers the roles itself and nothing is spawned.
    """
    categories, source, why = _categories(context)
    artifacts = [str(item) for item in context.get("challenge", {}).get("artifacts", [])]
    independent = len(categories) >= 2 or (len(artifacts) >= 2 and source != "default")
    mode: ExecutionMode = force_mode or ("delegated" if independent else "sequential")
    roles: list[str] = []
    if artifacts:
        roles.append("artifact-triage")
    roles += [f"{category}-specialist" for category in categories]
    roles.append("independent-critic")
    roles = list(dict.fromkeys(roles))[:4]
    if mode == "sequential":
        reason = "forced sequential" if force_mode else "simple problem: one category, at most one artifact"
        return WaveDecision(execution_mode=mode, required_roles=[], daybreak_covers=roles, categories=categories,
                            category_source=source, category_reason=why, reason=reason)
    reason = "forced delegated" if force_mode else (
        "two categories in play" if len(categories) >= 2 else "several artifacts plus a category")
    return WaveDecision(execution_mode=mode, required_roles=roles, daybreak_covers=[], categories=categories,
                        category_source=source, category_reason=why, reason=reason)


def select_model(tier: str, catalog: list[dict[str, Any]], *, current: str | None = None,
                 escalate: bool = False, escalation_reason: str | None = None) -> ModelSelection:
    """Choose only from the host-reported catalog; otherwise reuse the current model.

    ``catalog`` entries: {"id": "...", "tier": "lower|standard|strong"} as confirmed by the
    host at runtime. Names from documents are never invented.
    """
    wanted = "strong" if escalate else tier
    if escalate and not escalation_reason:
        raise ValueError("escalation needs a reason (a bounded attempt was inconclusive)")
    for entry in catalog:
        if entry.get("tier") == wanted and isinstance(entry.get("id"), str):
            return ModelSelection(requested_tier=wanted, model=entry["id"], source="catalog",  # type: ignore[arg-type]
                                  reason=escalation_reason or f"{wanted} tier available in the active catalog",
                                  escalated=escalate)
    return ModelSelection(requested_tier=wanted, model=current, source="current",  # type: ignore[arg-type]
                          reason=escalation_reason or "reuse the host's current model",
                          fallback_reason=f"no {wanted}-tier model in the active catalog", escalated=escalate)
