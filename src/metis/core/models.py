"""Provider-neutral messages and an explicitly deterministic local baseline."""
from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import Field, model_validator

from metis.core.contracts import ChallengeManifest, Contract
from metis.core.runtime import ToolRequest, ToolResult


class Decision(Contract):
    kind: Literal["tool", "candidate", "halt"]
    tool: ToolRequest | None = None
    candidate: str | None = Field(default=None, max_length=65_536)
    rationale: str | None = Field(default=None, min_length=5, max_length=500)

    @model_validator(mode="after")
    def check_shape(self) -> Decision:
        if self.kind == "tool" and self.tool is not None and self.candidate is None:
            return self
        if self.kind == "candidate" and self.candidate is not None and self.tool is None:
            return self
        if self.kind == "halt" and self.tool is None and self.candidate is None:
            return self
        raise ValueError("decision must have exactly the fields required by its kind")


class SolverContext(Contract):
    challenge: ChallengeManifest
    observations: tuple[ToolResult, ...] = ()
    last_tool: ToolRequest | None = None
    attempted_tools: tuple[ToolRequest, ...] = ()
    rejected_candidates: int = 0


class ModelProvider(Protocol):
    reservation_tokens: int
    reservation_cost: float

    def decide(self, context: SolverContext, *, timeout_seconds: float) -> Decision: ...


class FixtureProvider:
    """Deterministic decoder planner for generated fixtures, not an LLM substitute.

    Follows an explicit bounded tool plan. It takes a declared alternate only
    after matching parser-rejection evidence. No hidden-answer store or verifier
    object is reachable through its input.
    """

    reservation_tokens = 0
    reservation_cost = 0.0

    @staticmethod
    def _plan(context: SolverContext) -> tuple[list[ToolRequest], dict[tuple[int, int], str]]:
        spec = json.loads(context.challenge.description)
        if not isinstance(spec, dict):
            raise TypeError("invalid fixture plan")
        raw_attempts = spec.get("attempts")
        if not isinstance(raw_attempts, list) or not raw_attempts or len(raw_attempts) > 10:
            raise ValueError("invalid fixture attempts")
        attempts = [ToolRequest.model_validate(item) for item in raw_attempts]
        identities = [item.model_dump_json() for item in attempts]
        if len(set(identities)) != len(identities):
            raise ValueError("fixture attempts must be distinct")
        raw_fallbacks = spec.get("fallbacks", [])
        if not isinstance(raw_fallbacks, list) or len(raw_fallbacks) > 20:
            raise ValueError("invalid fixture fallbacks")
        fallbacks: dict[tuple[int, int], str] = {}
        for item in raw_fallbacks:
            if not isinstance(item, dict) or set(item) != {"after", "on", "try", "rationale"}:
                raise ValueError("fallback must specify after, on, try, and rationale")
            source, target = item["after"], item["try"]
            if (not isinstance(source, int) or isinstance(source, bool) or not 0 <= source < len(attempts)
                    or not isinstance(target, int) or isinstance(target, bool) or not 0 <= target < len(attempts)
                    or source == target):
                raise ValueError("fallback references an invalid attempt")
            # Only parser rejection is reliable evidence that a representation was wrong.
            if item["on"] != "invalid_input":
                raise ValueError("fallbacks may only use invalid_input evidence")
            if attempts[source].data != attempts[target].data:
                raise ValueError("parser-rejection fallbacks must preserve the challenge input")
            rationale = item["rationale"]
            if not isinstance(rationale, str) or not 5 <= len(rationale) <= 500:
                raise ValueError("fallback rationale must be 5..500 characters")
            key = (source, target)
            if key in fallbacks:
                raise ValueError("duplicate fallback route")
            fallbacks[key] = rationale
        return attempts, fallbacks

    def decide(self, context: SolverContext, *, timeout_seconds: float) -> Decision:
        attempts, fallbacks = self._plan(context)
        if context.observations and context.observations[-1].ok:
            if context.rejected_candidates == 0:
                return Decision(kind="candidate", candidate=context.observations[-1].output)
            return Decision(kind="halt")
        tried = list(context.attempted_tools)
        if not tried and context.last_tool is not None:
            tried = [context.last_tool]
        last_index = next((index for index, item in enumerate(attempts)
                           if context.last_tool == item), None)
        if context.observations and not context.observations[-1].ok:
            if context.last_tool is None or last_index is None or any(item not in attempts for item in tried):
                return Decision(kind="halt", rationale="Observed action is not part of the declared strategy plan.")
            routes = [(target, rationale) for (source, target), rationale in fallbacks.items()
                      if source == last_index]
            failure_kind = context.observations[-1].failure_kind
            if failure_kind in {"invalid_text", "execution_error", "timeout", "policy", None}:
                return Decision(kind="halt", rationale=(
                    "Observation is not parser-rejection evidence; stop without trying another strategy."))
            if routes:
                if failure_kind != "invalid_input":  # Defensive: route schema only permits this evidence.
                    return Decision(kind="halt", rationale="Configured fallback evidence did not match.")
                target_route = next(((target, rationale) for target, rationale in routes
                                     if attempts[target] not in tried), None)
                if target_route is None:
                    return Decision(kind="halt", rationale="Configured alternate was already attempted.")
                target, rationale = target_route
                return Decision(kind="tool", tool=attempts[target], rationale=rationale)
            return Decision(kind="halt", rationale="No evidence-conditioned fallback is declared for this action.")
        index = next((i for i, item in enumerate(attempts) if item not in tried), None)
        if index is None:
            return Decision(kind="halt")
        return Decision(kind="tool", tool=attempts[index])
