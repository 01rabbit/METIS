"""Bounded local-fixture observe/plan/act/verify loop, with metadata-only evidence."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Protocol
from uuid import uuid4

from metis.core.budgets import BudgetExhausted, BudgetTracker, Cancelled
from metis.core.contracts import ChallengeManifest, RunBudget, RunEvent, RunStatus
from metis.core.models import Decision, ModelProvider, SolverContext
from metis.core.runtime import ToolRequest, ToolResult
from metis.core.store import RunStore
from metis.core.verification import Verifier


class ToolRuntime(Protocol):
    def execute(self, request: ToolRequest, *, timeout_seconds: float) -> ToolResult: ...


class Runner:
    def __init__(self, store: RunStore, provider: ModelProvider, runtime: ToolRuntime,
                 verifier: Verifier, budget: RunBudget,
                 *, cancelled: Callable[[], bool] = lambda: False):
        self.store = store
        self.provider = provider
        self.runtime = runtime
        self.verifier = verifier
        self.budget = budget
        self.cancelled = cancelled

    def run(self, manifest: ChallengeManifest) -> str:
        # Re-validate a copy at the boundary; do not trust model_construct/mutation.
        challenge = ChallengeManifest.model_validate(manifest.model_dump())
        run_id = uuid4().hex
        sequence = 0
        tracker = BudgetTracker(self.budget)

        def emit(status: RunStatus, **detail: str) -> None:
            nonlocal sequence
            if status in {RunStatus.SOLVED, RunStatus.EXHAUSTED, RunStatus.ERROR,
                          RunStatus.CANCELLED, RunStatus.POLICY_DENIED}:
                detail.update(
                    actions=str(tracker.actions), model_tokens_reserved=str(tracker.tokens),
                    model_cost_reserved_usd=f"{tracker.cost:.6f}",
                    elapsed_seconds=f"{time.monotonic() - tracker.started:.6f}",
                    provider=type(self.provider).__name__,
                )
                usage = getattr(self.provider, "usage_totals", None)
                if isinstance(usage, dict):
                    detail["model_usage_observed"] = str(bool(getattr(self.provider, "usage_observed", False))).lower()
                    for key, value in usage.items():
                        detail[f"model_{key}"] = str(value)
                    detail["model_cost_usd"] = "unknown"
            self.store.append(RunEvent(run_id=run_id, sequence=sequence,
                                       status=status, detail=detail))
            sequence += 1

        def check() -> None:
            tracker.check(cancelled=self.cancelled())

        emit(RunStatus.NEW)
        context = SolverContext(challenge=challenge)
        seen: set[str] = set()
        try:
            check()
            # This fixture path deliberately rejects host artifacts and endpoints.
            if challenge.artifacts or challenge.scope.allowed_endpoints:
                emit(RunStatus.POLICY_DENIED, reason="fixture_scope_only")
                return run_id
            emit(RunStatus.VALIDATED)
            emit(RunStatus.CLASSIFIED)
            while True:
                emit(RunStatus.PLANNING)
                check()
                tracker.reserve_action()
                tracker.reserve_model(self.provider.reservation_tokens,
                                      self.provider.reservation_cost)
                decision = Decision.model_validate(self.provider.decide(context, timeout_seconds=min(
                    self.budget.per_tool_seconds, tracker.remaining_seconds(),
                )).model_dump())
                check()
                if decision.kind == "halt":
                    emit(RunStatus.EXHAUSTED, reason="provider_halted")
                    break
                if decision.kind == "candidate":
                    # Route through observation/verification, never accept a pattern match.
                    emit(RunStatus.EXECUTING, operation="submit_candidate")
                    emit(RunStatus.OBSERVING)
                    emit(RunStatus.VERIFYING)
                    assert decision.candidate is not None
                    if self.verifier.verify(challenge.challenge_id, decision.candidate):
                        check()
                        emit(RunStatus.SOLVED, verification="local_fixture_oracle")
                        break
                    context = context.model_copy(update={
                        "rejected_candidates": context.rejected_candidates + 1,
                    })
                    emit(RunStatus.REPLANNING, reason="candidate_rejected")
                    continue
                assert decision.tool is not None
                identity = hashlib.sha256(decision.tool.model_dump_json().encode()).hexdigest()
                if identity in seen:
                    emit(RunStatus.EXHAUSTED, reason="repeated_action")
                    break
                seen.add(identity)
                emit(RunStatus.EXECUTING, operation="isolated_fixture_tool", tool=decision.tool.tool,
                     action_identity=identity, rationale=decision.rationale or "")
                check()
                started = time.monotonic()
                observation = self.runtime.execute(decision.tool, timeout_seconds=min(
                    self.budget.per_tool_seconds, tracker.remaining_seconds(),
                ))
                check()
                if time.monotonic() - started > self.budget.per_tool_seconds:
                    raise BudgetExhausted("per-tool wall time")
                # Observe data in memory only; do not persist outputs/candidates.
                context = context.model_copy(update={
                    "observations": (*context.observations, observation),
                    "last_tool": decision.tool,
                })
                emit(RunStatus.OBSERVING, tool_ok=str(observation.ok).lower(), tool=decision.tool.tool,
                     failure_kind=observation.failure_kind or "none")
                emit(RunStatus.REPLANNING, reason=decision.rationale or "observation_recorded")
        except (Cancelled, KeyboardInterrupt):
            emit(RunStatus.CANCELLED)
        except BudgetExhausted:
            emit(RunStatus.EXHAUSTED, reason="budget_limit")
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError):
            # Provider/verifier/runtime errors can include secret input in their text.
            emit(RunStatus.ERROR, reason="component_failure")
        return run_id
