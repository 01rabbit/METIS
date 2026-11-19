"""Export answer-free held-out metrics from a validated METIS run ledger.

The manifest declares task metadata and run assignment. Outcome, resource use,
and verifier provenance come from the controller database, never the manifest.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import Field, model_validator

from metis.core.contracts import RunStatus
from metis.core.store import RunStore
from metis.evaluation.heldout_analysis import Arm, Budget, Identifier, Record, Study, Task, Trial
from metis.evaluation.verifier_provenance import (
    BROWSER_OBSERVED_VERIFICATION,
    OFFICIAL_VERIFICATIONS,
)

MAX_EVENTS = 100_000


class RunAssignment(Record):
    task_id: Identifier
    repetition: Annotated[int, Field(ge=0, le=19)]
    arm: Arm
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class ExportManifest(Record):
    schema_version: int = Field(ge=1, le=1)
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
    runs: Annotated[list[RunAssignment], Field(min_length=8, max_length=80_000)]

    @model_validator(mode="after")
    def complete_matrix(self) -> ExportManifest:
        if len(set(self.arms)) != len(self.arms) or self.baseline not in self.arms:
            raise ValueError("invalid arms")
        if set(self.budgets) != set(self.arms) or any(
            budget != self.budgets[self.baseline] for budget in self.budgets.values()
        ):
            raise ValueError("unequal arm budgets")
        task_ids = [task.task_id for task in self.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("duplicate task")
        expected = {(task_id, rep, arm) for task_id in task_ids
                    for rep in range(self.repetitions) for arm in self.arms}
        actual = [(run.task_id, run.repetition, run.arm) for run in self.runs]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            raise ValueError("incomplete or duplicate run matrix")
        if len({run.run_id for run in self.runs}) != len(self.runs):
            raise ValueError("run reused across trials")
        return self


def _trial(db: sqlite3.Connection, store: RunStore, assignment: RunAssignment,
           task: Task) -> Trial:
    count = db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (assignment.run_id,)).fetchone()[0]
    if count > MAX_EVENTS:
        raise ValueError("run event limit exceeded")
    events = store._read(db, assignment.run_id)
    if not events:
        raise ValueError("run evidence missing")
    row = db.execute("SELECT evaluation_split FROM codex_sessions WHERE run_id=?",
                     (assignment.run_id,)).fetchone()
    expected_split = "heldout" if task.split == "held_out" else "development"
    if row is None or row[0] != expected_split:
        raise ValueError("run split does not match the task")
    terminal = events[-1]
    verification = terminal.detail.get("verification", "")
    oracle: Literal["official", "protected_fixture", "browser_observed", "none"]
    if terminal.status == RunStatus.SOLVED and verification in OFFICIAL_VERIFICATIONS:
        oracle = "official"
    elif terminal.status == RunStatus.SOLVED and verification == BROWSER_OBSERVED_VERIFICATION:
        oracle = "browser_observed"
    elif terminal.status == RunStatus.SOLVED and verification == "local_fixture_oracle":
        oracle = "protected_fixture"
    else:
        oracle = "none"
    verified = oracle in {"official", "protected_fixture"}
    job_rows = db.execute("SELECT assignment_id,state,usage,model FROM agent_jobs WHERE run_id=?",
                          (assignment.run_id,)).fetchall()
    reports = {row[0] for row in db.execute(
        "SELECT assignment_id FROM ctf_agent_reports WHERE run_id=?", (assignment.run_id,))}
    complete = bool(job_rows) and all(state == "completed" and assignment_id in reports
                                      for assignment_id, state, _, _ in job_rows)
    reserved = db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                          (assignment.run_id,)).fetchone()[0]
    tokens = None
    if job_rows:
        usage = [json.loads(raw) if raw else None for _, _, raw, _ in job_rows]
        if all(isinstance(item, dict) and
               all(type(item.get(key)) is int and item[key] >= 0
                   for key in ("input_tokens", "output_tokens")) for item in usage):
            tokens = sum(cast(dict[str, int], item)["input_tokens"]
                         + cast(dict[str, int], item)["output_tokens"] for item in usage)
    times = db.execute("SELECT MIN(timestamp),MAX(timestamp) FROM events WHERE run_id=?",
                       (assignment.run_id,)).fetchone()
    started, ended = datetime.fromisoformat(times[0]), datetime.fromisoformat(times[1])
    if started.utcoffset() is None or ended.utcoffset() is None:
        raise ValueError("event timestamps lack timezone")
    seconds = (ended - started).total_seconds()
    if not 0 <= seconds <= 86_400:
        raise ValueError("event span is outside the benchmark bound")
    actions = sum(event.status == RunStatus.EXECUTING for event in events)
    failure: Literal["none", "budget", "incomplete", "unverified"]
    if verified and complete:
        failure = "none"
    elif terminal.status == RunStatus.CANCELLED or terminal.status == RunStatus.EXHAUSTED:
        failure = "budget"
    elif not complete:
        failure = "incomplete"
    else:
        failure = "unverified"
    return Trial(task_id=assignment.task_id, repetition=assignment.repetition,
                 arm=assignment.arm, run_id=assignment.run_id,
                 evidence_sequence=terminal.sequence, oracle=oracle,
                 oracle_verified=verified, workflow_complete=complete, failure=failure,
                 seconds=seconds, model_calls=reserved, actions=actions,
                 tokens=tokens, cost_usd=None)


def export(manifest: ExportManifest, database: Path) -> Study:
    """Read the ledger without creating tables or copying private run content."""
    manifest = ExportManifest.model_validate(manifest.model_dump())
    if database.is_symlink() or not database.is_file():
        raise ValueError("benchmark database unavailable")
    store = RunStore(database, read_only=True)
    tasks = {task.task_id: task for task in manifest.tasks}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        trials = [_trial(db, store, assignment, tasks[assignment.task_id])
                  for assignment in manifest.runs]
        if manifest.measurement == "real_model":
            for assignment in manifest.runs:
                models = [row[0] for row in db.execute(
                    "SELECT model FROM agent_jobs WHERE run_id=?", (assignment.run_id,))]
                if not models or any(model != manifest.model_pin for model in models):
                    raise ValueError("model pin does not match job records")
    return Study(schema_version=1, study_id=manifest.study_id,
                 measurement=manifest.measurement, model_pin=manifest.model_pin,
                 runtime_pin=manifest.runtime_pin, seed=manifest.seed,
                 repetitions=manifest.repetitions, arms=manifest.arms,
                 baseline=manifest.baseline, budgets=manifest.budgets,
                 tasks=manifest.tasks, trials=trials)


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[2] != "--database":
        print("usage: python -m metis.evaluation.heldout_export MANIFEST.json --database STATE.sqlite",
              file=sys.stderr)
        return 2
    try:
        raw = Path(sys.argv[1]).read_bytes()
        if len(raw) > 10_000_000:
            raise ValueError("oversized manifest")
        study = export(ExportManifest.model_validate_json(raw), Path(sys.argv[3]))
        print(study.model_dump_json())
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print("held-out export rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
