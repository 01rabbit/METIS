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
        # A failed Base64 parse is direct evidence against that representation.
        # Replan to the distinct hex transform instead of blindly advancing a
        # positional list; all other fixture plans retain their declared order.
        is_base64_hex_pair = (attempts and attempts[0].get("tool") == "base64_decode"
                              and len(attempts) == 2 and attempts[1].get("tool") == "hex_decode")
        if (context.observations and context.last_tool is not None
                and context.last_tool.tool == "base64_decode" and is_base64_hex_pair):
            if context.observations[-1].failure_kind == "invalid_input":
                return Decision(kind="tool", tool=ToolRequest.model_validate(attempts[1]),
                                rationale="Base64 decoder rejected input; test hex representation.")
            if not context.observations[-1].ok:
                return Decision(kind="halt", rationale=(
                    "Base64 attempt did not establish a parse mismatch; stop before guessing hex."))
        index = len(context.observations)
        if index >= len(attempts):
            return Decision(kind="halt")
        return Decision(kind="tool", tool=ToolRequest.model_validate(attempts[index]))
