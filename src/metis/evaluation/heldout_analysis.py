"""Validate and analyze answer-free, controller-exported P7 trial metrics.

This consumes evidence references; it neither authenticates them nor grants a
verification verdict. The exporter/reviewer must reconcile them with METIS.
"""
from __future__ import annotations

import json
import random
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metis.core.contracts import RunStatus
from metis.core.store import RunStore
from metis.evaluation.verifier_provenance import OFFICIAL_VERIFICATIONS

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@+-]{0,127}$")]
Count = Annotated[int, Field(ge=0, le=1_000_000_000)]
Seconds = Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)]
Money = Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)]
Arm = Literal["full", "without_memory", "without_planner", "single_agent"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Budget(Record):
    model_calls: Annotated[int, Field(ge=1, le=1000)]
    tokens: Annotated[int, Field(ge=1, le=10_000_000)]
    actions: Annotated[int, Field(ge=1, le=1000)]
    seconds: Annotated[float, Field(gt=0, le=86_400, allow_inf_nan=False)]
    cost_usd: Money | None


class Task(Record):
    task_id: Identifier
    category: Literal["crypto", "misc", "web", "rev", "pwn", "forensics"]
    difficulty: Literal["easy", "medium", "hard"]
    split: Literal["development", "held_out"]
    exposure: Literal["unseen", "prior_solved", "prior_answer", "unknown"]
    solvability_control_verified: bool


class Trial(Record):
    task_id: Identifier
    repetition: Annotated[int, Field(ge=0, le=19)]
    arm: Arm
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    evidence_sequence: Annotated[int, Field(ge=1)]
    oracle: Literal["official", "protected_fixture", "browser_observed", "archive_local", "none"]
    oracle_verified: bool
    workflow_complete: bool
    failure: Literal["none", "incorrect", "incomplete", "timeout", "budget", "policy",
                     "provider", "tool", "unverified"]
    seconds: Seconds
    model_calls: Count
    actions: Count
    tokens: Count | None
    cost_usd: Money | None

    @model_validator(mode="after")
    def consistent_outcome(self) -> Trial:
        if self.oracle_verified and self.oracle == "none":
            raise ValueError("verified outcome requires a verifier provenance")
        if self.failure == "none" and not (self.oracle_verified and self.workflow_complete):
            raise ValueError("successful outcome requires oracle and workflow completion")
        if self.failure != "none" and self.oracle_verified and self.workflow_complete:
            raise ValueError("completed verified outcome cannot carry a failure")
        return self


class Study(Record):
    schema_version: Literal[1]
    study_id: Identifier
    measurement: Literal["synthetic_fixture", "real_model"]
    model_pin: Identifier
    runtime_pin: Identifier
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    repetitions: Annotated[int, Field(ge=2, le=20)]
    arms: Annotated[list[Arm], Field(min_length=2, max_length=4)]
    baseline: Arm
    budgets: dict[Arm, Budget]
    tasks: Annotated[list[Task], Field(min_length=2, max_length=1000)]
    trials: Annotated[list[Trial], Field(min_length=8, max_length=80_000)]

    @model_validator(mode="after")
    def matched_design(self) -> Study:
        if len(set(self.arms)) != len(self.arms) or self.baseline not in self.arms:
            raise ValueError("arms must be unique and contain the baseline")
        if set(self.budgets) != set(self.arms):
            raise ValueError("each arm requires a budget")
        if any(budget != self.budgets[self.baseline] for budget in self.budgets.values()):
            raise ValueError("arm budgets must be identical aggregate caps")
        task_ids = {task.task_id for task in self.tasks}
        if len(task_ids) != len(self.tasks):
            raise ValueError("duplicate task identifier")
        expected = {(task, rep, arm) for task in task_ids
                    for rep in range(self.repetitions) for arm in self.arms}
        actual = [(trial.task_id, trial.repetition, trial.arm) for trial in self.trials]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            raise ValueError("trials must form an exact complete paired repeated matrix")
        if len({trial.run_id for trial in self.trials}) != len(self.trials):
            raise ValueError("every trial requires an independent fresh run identifier")
        return self


def _interval(values: list[float], *, seed: int, samples: int) -> list[float]:
    """Resample task means; repetitions stay together within each task cluster."""
    rng = random.Random(seed)
    estimates = sorted(statistics.mean(rng.choices(values, k=len(values)))
                       for _ in range(samples))
    return [round(estimates[int((samples - 1) * quantile)], 6)
            for quantile in (0.025, 0.975)]


def _analyze(study: Study, *, samples: int, control_attestation_verified: bool) -> dict:
    # Revalidate constructed/mutated objects at the trust boundary.
    study = Study.model_validate(study.model_dump())
    if not 100 <= samples <= 20_000:
        raise ValueError("bootstrap samples must be 100..20000")
    tasks = {task.task_id: task for task in study.tasks}
    rows = {(trial.task_id, trial.repetition, trial.arm): trial for trial in study.trials}
    exclusions: Counter[str] = Counter()
    scored: dict[tuple[str, int, str], int] = {}
    acceptance_scored: dict[tuple[str, int, str], int] = {}
    resource_ineligible: Counter[str] = Counter()
    overruns: Counter[str] = Counter()
    for key, trial in rows.items():
        task = tasks[trial.task_id]
        budget = study.budgets[trial.arm]
        exposure_eligible = task.split == "held_out" and task.exposure == "unseen"
        eligible = exposure_eligible and task.solvability_control_verified
        if not exposure_eligible:
            exclusions[f"{task.split}:{task.exposure}"] += 1
        exceeded = any((trial.model_calls > budget.model_calls, trial.actions > budget.actions,
                        trial.seconds > budget.seconds,
                        trial.tokens is not None and trial.tokens > budget.tokens,
                        budget.cost_usd is not None and trial.cost_usd is not None
                        and trial.cost_usd > budget.cost_usd))
        if exceeded:
            overruns[trial.arm] += 1
        scored[key] = int(eligible and not exceeded and trial.failure == "none"
                          and trial.oracle in {"official", "protected_fixture"}
                          and trial.oracle_verified and trial.workflow_complete)
        resources_complete = (trial.tokens is not None and trial.cost_usd is not None
                              and budget.cost_usd is not None)
        if not resources_complete:
            resource_ineligible[trial.arm] += 1
        acceptance_scored[key] = scored[key] * int(resources_complete and control_attestation_verified)
    arms = {}
    task_means: dict[str, list[float]] = {}
    acceptance_task_means: dict[str, list[float]] = {}
    for arm in study.arms:
        trials = [trial for trial in study.trials if trial.arm == arm]
        means = [statistics.mean(scored[(task, rep, arm)]
                                 for rep in range(study.repetitions)) for task in tasks]
        task_means[arm] = means
        acceptance_means = [statistics.mean(acceptance_scored[(task, rep, arm)]
                                            for rep in range(study.repetitions)) for task in tasks]
        acceptance_task_means[arm] = acceptance_means
        arms[arm] = {
            "trials": len(trials), "scored_solves": sum(scored[(t.task_id, t.repetition, arm)]
                                                        for t in trials),
            "solve_rate": statistics.mean(means),
            "acceptance_eligible_solves": (sum(acceptance_scored[(t.task_id, t.repetition, arm)]
                                                for t in trials)
                                           if control_attestation_verified else None),
            "acceptance_eligible_solve_rate": (statistics.mean(acceptance_means)
                                                if control_attestation_verified else None),
            "acceptance_eligible_solve_rate_cluster_bootstrap_95_interval": (
                _interval(acceptance_means, seed=study.seed, samples=samples)
                if control_attestation_verified else None
            ),
            "acceptance_ineligible_resource_trials": resource_ineligible[arm],
            "cost_cap_declared": study.budgets[arm].cost_usd is not None,
            "solve_rate_cluster_bootstrap_95_interval": _interval(
                means, seed=study.seed, samples=samples),
            "mean_seconds": statistics.mean(t.seconds for t in trials),
            "median_seconds": statistics.median(t.seconds for t in trials),
            "mean_model_calls": statistics.mean(t.model_calls for t in trials),
            "mean_actions": statistics.mean(t.actions for t in trials),
            "mean_tokens": (statistics.mean(t.tokens for t in trials if t.tokens is not None)
                            if all(t.tokens is not None for t in trials) else None),
            "total_cost_usd": (sum(t.cost_usd for t in trials if t.cost_usd is not None)
                               if all(t.cost_usd is not None for t in trials) else None),
            "unknown_token_trials": sum(t.tokens is None for t in trials),
            "unknown_cost_trials": sum(t.cost_usd is None for t in trials),
            "budget_overrun_trials": overruns[arm],
            "declared_failures": dict(Counter(t.failure for t in trials if t.failure != "none")),
            "untrusted_oracle_trials": sum(t.oracle not in {"official", "protected_fixture"}
                                           for t in trials),
        }
    comparisons = {}
    for arm in study.arms:
        if arm == study.baseline:
            continue
        deltas = [value - baseline for value, baseline in
                  zip(task_means[arm], task_means[study.baseline], strict=True)]
        comparisons[f"{arm}_minus_{study.baseline}"] = {
            "paired_solve_rate_difference": statistics.mean(deltas),
            "paired_cluster_bootstrap_95_interval": _interval(
                deltas, seed=study.seed, samples=samples),
        }
        acceptance_deltas = [value - baseline for value, baseline in zip(
            acceptance_task_means[arm], acceptance_task_means[study.baseline], strict=True)]
        comparisons[f"{arm}_minus_{study.baseline}"].update({
            "paired_acceptance_eligible_solve_rate_difference": (
                statistics.mean(acceptance_deltas) if control_attestation_verified else None
            ),
            "paired_acceptance_eligible_cluster_bootstrap_95_interval": (
                _interval(acceptance_deltas, seed=study.seed, samples=samples)
                if control_attestation_verified else None
            ),
        })
    return {
        "study_id": study.study_id, "measurement": study.measurement,
        "model_pin": study.model_pin, "runtime_pin": study.runtime_pin,
        "distinct_task_clusters": len(tasks), "repetitions": study.repetitions,
        "matched_aggregate_budgets": {a: b.model_dump() for a, b in study.budgets.items()},
        "solve_metric_roles": {
            "scored_solves": "diagnostic; unknown tokens/cost or absent cost cap may remain",
            "acceptance_eligible_solves": (
                "requires authenticated independent controls, actual tokens/cost and declared cost cap"
            ),
        },
        "acceptance_control_attestation_verified": control_attestation_verified,
        "unauthenticated_control_excluded_trials": 0 if control_attestation_verified else len(study.trials),
        "arms": arms, "comparisons": comparisons,
        "contamination_excluded_trials": dict(exclusions),
        "unresolved_solvability_control_excluded_trials": sum(
            not tasks[trial.task_id].solvability_control_verified for trial in study.trials),
        "solvability_controls_missing": sum(not task.solvability_control_verified
                                            for task in study.tasks),
        "strata_task_counts": dict(Counter(f"{t.category}:{t.difficulty}" for t in study.tasks)),
        "bootstrap": {"unit": "task_id", "samples": samples, "seed": study.seed},
        "limitations": [
            "Evidence references and exposure declarations require independent ledger review.",
            "Synthetic fixtures measure the analysis path, not model or CTF performance.",
            "Unknown usage/cost remain null; equal caps do not imply equal actual consumption.",
            "Resource-incomplete trials score zero for acceptance eligibility and remain in denominators.",
            "Cluster intervals describe selected tasks; all-equal samples give degenerate intervals.",
            "Prior model-training exposure cannot be ruled out by a clean local exposure declaration.",
        ],
    }


def analyze(study: Study, *, samples: int = 10_000) -> dict:
    """Produce diagnostic metrics; unsigned controls never produce acceptance scores."""
    return _analyze(study, samples=samples, control_attestation_verified=False)


def _analyze_with_verified_controls(study: Study, *, samples: int = 10_000) -> dict:
    """Internal path used only after heldout_protocol verifies a detached signature."""
    return _analyze(study, samples=samples, control_attestation_verified=True)


def reconcile_evidence(study: Study, database: Path) -> dict[str, int]:
    """Reconcile every trial reference against a validated read-only METIS ledger.

    This checks event-chain provenance and successful-verdict event type. It does
    not authenticate protected-fixture declarations, exposure, model pins, or
    actual resource measurements.
    """
    study = Study.model_validate(study.model_dump())
    store = RunStore(database, read_only=True)
    reconciled = 0
    official_verified = 0
    fixture_verified = 0
    for trial in study.trials:
        events = store.read(trial.run_id)
        if trial.evidence_sequence >= len(events):
            raise ValueError("trial evidence reference is outside the run event chain")
        event = events[trial.evidence_sequence]
        if event.sequence != trial.evidence_sequence:
            raise ValueError("trial evidence reference does not match its event")
        if trial.oracle_verified:
            verification = event.detail.get("verification", "")
            if event.status != RunStatus.SOLVED:
                raise ValueError("verified trial does not reference a SOLVED event")
            if trial.oracle == "official":
                if verification not in OFFICIAL_VERIFICATIONS:
                    raise ValueError("official trial lacks an official verifier event")
                official_verified += 1
            elif trial.oracle == "protected_fixture":
                if verification != "local_fixture_oracle":
                    raise ValueError("fixture trial lacks a protected fixture verdict event")
                fixture_verified += 1
            else:
                raise ValueError("untrusted oracle cannot verify a trial")
        reconciled += 1
    return {"trials_reconciled": reconciled, "official_verified_trials": official_verified,
            "protected_fixture_verified_trials": fixture_verified}


def main() -> int:
    if len(sys.argv) not in {2, 4} or (len(sys.argv) == 4 and sys.argv[2] != "--database"):
        print("usage: python -m metis.evaluation.heldout_analysis METRICS.json [--database STATE.sqlite]",
              file=sys.stderr)
        return 2
    try:
        path = Path(sys.argv[1])
        with path.open("rb") as stream:
            payload = stream.read(10_000_001)
        if len(payload) > 10_000_000:
            raise ValueError("oversized metrics")
        study = Study.model_validate_json(payload)
        result = analyze(study)
        if len(sys.argv) == 4:
            reconciliation = reconcile_evidence(study, Path(sys.argv[3]))
            result["ledger_reconciliation"] = reconciliation
    except (OSError, ValueError, TypeError, sqlite3.Error):
        # Pydantic errors include rejected input; never print them into public logs.
        print("benchmark metrics rejected; review locally against the schema", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
