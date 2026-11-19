"""Deterministic, oracle-free checks for the sequential Issue #6 treatment."""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Reconstruction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbols: tuple[str, ...] = Field(min_length=8, max_length=32)
    precedences: tuple[tuple[str, str], ...] = Field(min_length=7, max_length=256)


class Counterexample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["missing", "duplicate", "unknown", "precedence"]
    symbol: str | None = None
    before: str | None = None
    after: str | None = None


@dataclass(frozen=True)
class CheckedCounterexample:
    valid: bool
    reason: str


def validate_counterexample(task: Reconstruction, proposal: tuple[str, ...],
                            claim: Counterexample) -> CheckedCounterexample:
    """Check the claimed witness using public constraints, never the hidden order."""
    expected = set(task.symbols)
    if claim.kind == "missing":
        valid = claim.symbol in expected and claim.symbol not in proposal
    elif claim.kind == "duplicate":
        valid = claim.symbol in expected and proposal.count(claim.symbol) > 1
    elif claim.kind == "unknown":
        valid = claim.symbol not in expected and claim.symbol in proposal
    else:
        pair = (claim.before, claim.after)
        valid = (pair in task.precedences and claim.before in proposal and claim.after in proposal
                 and proposal.index(claim.before) >= proposal.index(claim.after))
    return CheckedCounterexample(bool(valid), "validated public constraint" if valid else "invalid witness")


def first_counterexample(task: Reconstruction, proposal: tuple[str, ...]) -> Counterexample | None:
    """Deterministic test oracle for local tests and final public-constraint scoring."""
    for symbol in task.symbols:
        if symbol not in proposal:
            return Counterexample(kind="missing", symbol=symbol)
        if proposal.count(symbol) > 1:
            return Counterexample(kind="duplicate", symbol=symbol)
    for symbol in proposal:
        if symbol not in task.symbols:
            return Counterexample(kind="unknown", symbol=symbol)
    for before, after in task.precedences:
        if proposal.index(before) >= proposal.index(after):
            return Counterexample(kind="precedence", before=before, after=after)
    return None


def make_task(seed: int, *, size: int = 20) -> tuple[Reconstruction, tuple[str, ...]]:
    """Produce a fresh shuffled reconstruction instance with a unique valid order."""
    if not 8 <= size <= 32:
        raise ValueError("size must be in [8, 32]")
    rng = random.Random(seed)
    order = [f"s{index:02d}" for index in range(size)]
    rng.shuffle(order)
    edges = {(order[index], order[index + 1]) for index in range(size - 1)}
    for _ in range(size * 3):
        left = rng.randrange(size - 1)
        right = rng.randrange(left + 1, size)
        edges.add((order[left], order[right]))
    symbols = order.copy()
    rng.shuffle(symbols)
    precedences = sorted(edges)
    rng.shuffle(precedences)
    task = Reconstruction(symbols=tuple(symbols), precedences=tuple(precedences))
    return task, tuple(order)


def analyze_paired(data: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen paired gate to answer-free retained outcomes."""
    if (data.get("study") != "issue6-owner-falsifier-2026-11-19"
            or data.get("seed") != 2026111906
            or data.get("arms") != ["single", "owner_falsifier"]):
        raise ValueError("study identity does not match preregistration")
    records = data.get("records")
    if not isinstance(records, list) or len(records) != 60:
        raise ValueError("expected exactly 60 arm records")
    by_key = {(row["case"], row["arm"]): row for row in records}
    cases = [f"task-{index:02d}" for index in range(30)]
    if len(by_key) != 60 or set(by_key) != {(case, arm) for case in cases
                                           for arm in ("single", "owner_falsifier")}:
        raise ValueError("missing or duplicate paired arm")
    deltas: list[int] = []
    discordance = {"both": 0, "owner_falsifier_only": 0, "single_only": 0, "neither": 0}
    for case in cases:
        single = by_key[(case, "single")]["workflow_verified"] is True
        combined = by_key[(case, "owner_falsifier")]["workflow_verified"] is True
        deltas.append(int(combined) - int(single))
        key = ("both" if single and combined else "owner_falsifier_only" if combined
               else "single_only" if single else "neither")
        discordance[key] += 1
    rng = random.Random(2026111906)
    estimates = sorted(statistics.mean(rng.choice(deltas) for _ in deltas)
                       for _ in range(10_000))
    interval = [estimates[249], estimates[9749]]
    return {"clusters": 30, "paired_difference": round(statistics.mean(deltas), 4),
            "bootstrap_95_interval": [round(value, 4) for value in interval],
            "gain_gate_met": interval[0] > 0, "discordance": discordance,
            "bootstrap_samples": 10_000, "bootstrap_seed": 2026111906}
