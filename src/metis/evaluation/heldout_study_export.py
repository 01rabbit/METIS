"""Export answer-free held-out metrics from a validated METIS run ledger.

The manifest declares task metadata and run assignment. Outcome, resource use,
and verifier provenance come from the controller database, never the manifest.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from metis.core.contracts import RunStatus
from metis.core.store import RunStore
from metis.evaluation.heldout_analysis import Arm, Budget, Identifier, Record, Study, Task, Trial
from metis.evaluation.verifier_provenance import (
    BROWSER_OBSERVED_VERIFICATION,
    OFFICIAL_VERIFICATIONS,
)

MAX_EVENTS = 100_000
_MAX_EXPORTED_TOKENS = 1_000_000_000  # heldout_analysis.Trial.tokens limit
_ATTEMPT_ID = re.compile(r"[0-9a-f]{16}")


def _job_model(value: str | None) -> str | None:
    """Read both legacy plain pins and scheduler model-selection records."""
    if value is None:
        return None
    if not value.startswith("{"):
        return value
    try:
        record = json.loads(value)
    except json.JSONDecodeError:
        return None
    return record.get("model") if isinstance(record, dict) and isinstance(record.get("model"), str) else None


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


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous telemetry")
        result[key] = value
    return result


def _metric_record(raw: str | None) -> dict[str, object] | None:
    if not isinstance(raw, str) or len(raw) > 16_384:
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_unique_keys)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _coverage_available(db: sqlite3.Connection) -> bool:
    required = {
        "agent_jobs": {"attempt_id", "attempt_no"},
        "agent_turn_reservations": {"id", "attempt_id"},
        "agent_job_log": {"assignment_id", "attempt_id", "event", "detail"},
    }
    return all(columns.issubset({row[1] for row in db.execute(f"PRAGMA table_info({table})")})
               for table, columns in required.items())


def _covered_tokens(db: sqlite3.Connection, run_id: str,
                    job_rows: list[tuple[str, str, str | None, str | None, int]],
                    reserved: int) -> int | None:
    """Return observed CLI totals only when all charged attempts have coverage."""
    if not 0 < reserved <= MAX_EVENTS:
        return None
    by_job: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for reservation_id, assignment_id, attempt_id in db.execute(
        "SELECT id, assignment_id, attempt_id FROM agent_turn_reservations WHERE run_id=?",
        (run_id,),
    ):
        by_job[assignment_id].append((reservation_id, attempt_id))
    total = 0
    for assignment_id, _, raw, attempt_id, attempt_no in job_rows:
        charges = by_job.pop(assignment_id, [])
        if not charges:
            if raw is not None or db.execute(
                "SELECT 1 FROM agent_job_log WHERE assignment_id=? AND event='codex_turn' LIMIT 1",
                (assignment_id,),
            ).fetchone():
                return None
            continue
        # The aggregate belongs to the mutable job row and carries no attempt ID.
        # Even a later attempt with complete-looking metadata cannot disprove stale usage.
        if not isinstance(attempt_id, str) or not _ATTEMPT_ID.fullmatch(attempt_id) or attempt_no != 1 or any(
            charged_attempt != attempt_id for _, charged_attempt in charges
        ):
            return None
        usage = _metric_record(raw)
        if usage is None or usage.get("host") != "codex-exec":
            return None
        turns, input_tokens, output_tokens = (usage.get(key) for key in ("turns", "input_tokens", "output_tokens"))
        if (type(turns) is not int or turns != len(charges) or type(input_tokens) is not int
                or type(output_tokens) is not int or input_tokens <= 0 or output_tokens <= 0):
            return None
        observed = set()
        for (detail,) in db.execute(
            "SELECT detail FROM agent_job_log WHERE assignment_id=? AND attempt_id=? AND event='codex_turn' LIMIT ?",
            (assignment_id, attempt_id, len(charges) + 1),
        ):
            record = _metric_record(detail)
            identity = record.get("reservation_id") if record is not None else None
            if type(identity) is not int or identity in observed:
                return None
            observed.add(identity)
        if observed != {reservation_id for reservation_id, _ in charges}:
            return None
        total += input_tokens + output_tokens
        if total > _MAX_EXPORTED_TOKENS:
            return None
    return total if not by_job else None


def _trial(db: sqlite3.Connection, store: RunStore, assignment: RunAssignment,
           task: Task, *, token_coverage: bool) -> Trial:
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
    attempts = "attempt_id, attempt_no" if token_coverage else "NULL, 0"
    job_rows = db.execute(f"SELECT assignment_id,state,usage,{attempts} FROM agent_jobs WHERE run_id=?",
                          (assignment.run_id,)).fetchall()
    reports = {row[0] for row in db.execute(
        "SELECT assignment_id FROM ctf_agent_reports WHERE run_id=?", (assignment.run_id,))}
    complete = bool(job_rows) and all(state == "completed" and assignment_id in reports
                                      for assignment_id, state, _, _, _ in job_rows)
    reserved = db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                          (assignment.run_id,)).fetchone()[0]
    tokens = _covered_tokens(db, assignment.run_id, job_rows, reserved) if token_coverage else None
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
        token_coverage = _coverage_available(db)
        trials = [_trial(db, store, assignment, tasks[assignment.task_id], token_coverage=token_coverage)
                  for assignment in manifest.runs]
        if manifest.measurement == "real_model":
            for assignment in manifest.runs:
                models = [row[0] for row in db.execute(
                    "SELECT model FROM agent_jobs WHERE run_id=?", (assignment.run_id,))]
                if not models or any(_job_model(model) != manifest.model_pin for model in models):
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
