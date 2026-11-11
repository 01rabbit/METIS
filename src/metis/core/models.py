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
    rejected_candidates: int = 0


class ModelProvider(Protocol):
    reservation_tokens: int
    reservation_cost: float

    def decide(self, context: SolverContext, *, timeout_seconds: float) -> Decision: ...


class FixtureProvider:
    """Deterministic decoder planner for generated fixtures, not an LLM substitute.

    Supports ordered alternative transforms so failure can trigger replanning.
    No hidden-answer store or verifier object is reachable through its input.
    """

    reservation_tokens = 0
    reservation_cost = 0.0

    def decide(self, context: SolverContext, *, timeout_seconds: float) -> Decision:
        spec = json.loads(context.challenge.description)
        attempts = spec["attempts"]
        if not isinstance(attempts, list) or len(attempts) > 10:
            raise ValueError("invalid fixture attempts")
        if context.observations and context.observations[-1].ok:
            if context.rejected_candidates == 0:
                return Decision(kind="candidate", candidate=context.observations[-1].output)
            return Decision(kind="halt")
        index = len(context.observations)
        if index >= len(attempts):
            return Decision(kind="halt")
        return Decision(kind="tool", tool=ToolRequest.model_validate(attempts[index]))
