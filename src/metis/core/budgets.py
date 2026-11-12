"""Controller-owned limits. Solver messages cannot change these limits."""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from metis.core.contracts import RunBudget


class BudgetExhausted(Exception):
    pass


class Cancelled(Exception):
    pass


class BudgetTracker:
    def __init__(self, budget: RunBudget, *, clock: Callable[[], float] = time.monotonic):
        self.budget = RunBudget.model_validate(budget.model_dump())
        self.clock = clock
        self.started = clock()
        self.actions = 0
        self.tokens = 0
        self.cost = 0.0

    def check(self, *, cancelled: bool = False) -> None:
        if cancelled:
            raise Cancelled
        if self.clock() - self.started >= self.budget.wall_time_seconds:
            raise BudgetExhausted("wall time")

    def reserve_action(self) -> None:
        self.check()
        if self.actions >= self.budget.max_actions:
            raise BudgetExhausted("actions")
        self.actions += 1

    def reserve_model(self, tokens: int, cost: float) -> None:
        """Conservatively charge configured call maxima before contacting a provider.

        Reservations are never refunded, including failed/invalid responses.
        The provider must enforce its declared upper bounds itself.
        """
        self.check()
        if tokens < 0 or not math.isfinite(cost) or cost < 0:
            raise ValueError("invalid model reservation")
        if self.tokens + tokens > self.budget.max_model_tokens:
            raise BudgetExhausted("model tokens")
        if self.cost + cost > self.budget.max_cost_usd:
            raise BudgetExhausted("model cost")
        self.tokens += tokens
        self.cost += cost

    def remaining_seconds(self) -> float:
        return max(0.0, self.budget.wall_time_seconds - (self.clock() - self.started))
