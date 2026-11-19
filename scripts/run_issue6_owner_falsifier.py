#!/usr/bin/env python3
"""Prospective Issue #6 owner/falsifier study; requires explicit --execute."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI, run_assignment
from metis.core.ctf_orchestration import AgentLedger
from metis.evaluation.issue6_owner_falsifier import (
    Counterexample, Reconstruction, make_task, validate_counterexample,
)

STUDY = "issue6-owner-falsifier-2026-11-19"
SEED = 2026111906
MODEL = "gpt-6.1-sol"
CLI = "0.169.0"
ARMS = ("single", "owner_falsifier")
CALLS = 14
ACTIONS = 9
OUTPUT = Path("docs/reports/data/issue6-owner-falsifier-2026-11-19.json")
STATE = Path.home() / ".local/state/metis/issue6-owner-falsifier-2026-11-19"


class PinnedCodexCLI(CodexCLI):
    def argv(self, workdir: Path, schema: Path, output: Path, model: str | None) -> list[str]:
        command = super().argv(workdir, schema, output, model)
        return [*command[:-1], "-c", 'model_reasoning_effort="low"', command[-1]]


def _wave(ledger: AgentLedger, run_id: str, artifact: str, role: str, max_turns: int,
          *, reason: str | None = None) -> dict[str, Any]:
    plan = ledger.create_wave(run_id, mode="delegated", reason=reason)
    assignments = plan["assignments"]
    chosen = next((dict(item) for item in assignments if item["role"] == role), None)
    if chosen is None:
        chosen = dict(assignments[0])
        chosen["role"] = role
    chosen["inputs"] = {"artifacts": [artifact]}
    chosen["max_turns"] = max_turns
    chosen["objective"] = "Reconstruct or check an ordering using only the assigned public constraints."
    plan["assignments"] = [chosen]
    plan["decision"]["required_roles"] = [role]
    plan["daybreak_covers"] = []
    with sqlite3.connect(ledger.database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    return plan


def _candidate(scheduler: AgentScheduler, run_id: str, assignment_id: str) -> str | None:
    rows = scheduler.candidates(run_id)
    matches = [row for row in rows if row["assignment_id"] == assignment_id
               and row["state"] == "pending" and row.get("candidate_file")]
    if len(matches) != 1:
        return None
    return Path(matches[0]["candidate_file"]).read_text(encoding="utf-8").strip()


def _run_wave(scheduler: AgentScheduler, runner: PinnedCodexCLI, run_id: str,
              plan: dict[str, Any], note: str) -> tuple[dict[str, Any], str | None, bool]:
    scheduler.enqueue(run_id, plan["wave_id"])
    jobs = scheduler.dispatch(run_id)["started"]
    if len(jobs) != 1:
        return {"job_state": "not_dispatched", "codex_turns": []}, None, False
    job = jobs[0]
    result = run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"],
                            runner, model=MODEL, turn_timeout=180, note=note)
    synthesis = scheduler.ledger.synthesize(run_id, plan["wave_id"])
    return result, _candidate(scheduler, run_id, job["assignment_id"]), bool(synthesis["complete"])


def _parse_order(raw: str | None, task: Reconstruction) -> tuple[str, ...] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (not isinstance(value, list) or len(value) != len(task.symbols)
            or any(not isinstance(item, str) for item in value)):
        return None
    return tuple(value)


def run_arm(session: CodexSession, scheduler: AgentScheduler, runner: PinnedCodexCLI,
            root: Path, case_id: str, task: Reconstruction, answer: tuple[str, ...],
            arm: str) -> dict[str, Any]:
    started = time.monotonic()
    artifact = root / f"{case_id}-{arm}.json"
    artifact.write_text(task.model_dump_json(), encoding="utf-8")
    run_id = session.intake(
        title=f"Synthetic ordering reconstruction {case_id}",
        description=("Reconstruct a permutation of the listed symbols satisfying every directed "
                     "precedence pair. Submit a JSON string array privately. Use only the supplied artifact."),
        paths=[artifact], categories=["misc"], max_actions=ACTIONS, wall_seconds=600,
        evaluation_split="heldout")["run_id"]
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=CALLS,
                        catalog=[{"id": MODEL, "tier": "standard"}], current_model=MODEL,
                        memory_retrieval=False)
    refs = session.context(run_id)["challenge"]["artifacts"]
    results: list[dict[str, Any]] = []
    complete: list[bool] = []
    owner_plan = _wave(scheduler.ledger, run_id, refs[0], "crypto-specialist",
                       12 if arm == "single" else 6)
    owner_note = ("Return one private JSON array containing each symbol exactly once in an order "
                  "satisfying all precedence pairs. Check constraints before candidate_report; "
                  "do not include the array in report text.")
    owner_result, raw, owner_complete = _run_wave(scheduler, runner, run_id, owner_plan, owner_note)
    results.append(owner_result)
    complete.append(owner_complete)
    proposal = _parse_order(raw, task)
    witness_valid = False
    repair_attempted = False
    if (arm == "owner_falsifier" and proposal is not None and owner_complete
            and owner_result.get("job_state") == "completed"):
        try:
            check_plan = _wave(scheduler.ledger, run_id, refs[0], "forensics-specialist", 3,
                               reason="Fresh-context search for a concrete public constraint violation")
        except ValueError:
            check_plan = None
        if check_plan is not None:
            check_note = ("Inspect the public constraints and this provisional order: "
                          + json.dumps(proposal) + ". Find one concrete violated input constraint. "
                          "Never use an oracle. Return a private JSON object with kind missing, duplicate, "
                          "unknown, or precedence and the corresponding symbol or before/after fields. "
                          "If no violation exists, report completion without a candidate. Do not copy the "
                          "provisional order into report text.")
            check_result, raw_witness, check_complete = _run_wave(
                scheduler, runner, run_id, check_plan, check_note)
            results.append(check_result)
            complete.append(check_complete)
            try:
                claim = Counterexample.model_validate_json(raw_witness or "")
                witness_valid = validate_counterexample(task, proposal, claim).valid
            except ValidationError:
                claim = None
            if (witness_valid and claim is not None and check_complete
                    and check_result.get("job_state") == "completed"):
                try:
                    repair_plan = _wave(scheduler.ledger, run_id, refs[0], "crypto-specialist", 3,
                                        reason="Repair only the independently validated public constraint witness")
                except ValueError:
                    repair_plan = None
                if repair_plan is not None:
                    repair_attempted = True
                    repair_note = ("Repair your provisional JSON order " + json.dumps(proposal)
                                   + " using this independently validated input-constraint witness "
                                   + claim.model_dump_json() + ". Return the entire corrected order privately "
                                   "using candidate_report; do not place the order in report text.")
                    repair_result, repaired_raw, repair_complete = _run_wave(
                        scheduler, runner, run_id, repair_plan, repair_note)
                    results.append(repair_result)
                    complete.append(repair_complete)
                    repaired = _parse_order(repaired_raw, task)
                    if (repaired is not None and repair_complete
                            and repair_result.get("job_state") == "completed"):
                        proposal = repaired
    # Both arms pass through this identical finalizer. Only the controller sees the answer.
    required_stages_present = bool(arm == "single" or len(results) >= 2)
    if witness_valid:
        required_stages_present = required_stages_present and repair_attempted and len(results) == 3
    workflow_complete = bool(required_stages_present and all(complete)
                             and all(result.get("job_state") == "completed" for result in results))
    verified = bool(workflow_complete and proposal == answer)
    public_constraints_valid = bool(workflow_complete and proposal is not None
                                    and len(set(proposal)) == len(task.symbols)
                                    and set(proposal) == set(task.symbols)
                                    and all(proposal.index(a) < proposal.index(b)
                                            for a, b in task.precedences))
    turns = [turn for result in results for turn in result.get("codex_turns", [])]
    budget = scheduler.model_turn_budget(run_id)
    scheduler.candidates(run_id, purge="all")
    usage_reported = sum(turn.get("usage") is not None for turn in turns)
    return {"case": case_id, "arm": arm, "run_id": run_id,
            "oracle_verified": verified,
            "workflow_verified": verified,
            "public_constraints_valid": public_constraints_valid,
            "witness_valid": witness_valid, "repair_attempted": repair_attempted,
            "synthesis_complete": all(complete), "workflow_complete": workflow_complete,
            "job_states": [job["state"] for job in scheduler.jobs(run_id)],
            "stage_states": [result.get("job_state") for result in results],
            "calls_observed": len(turns), "calls_reserved": budget["reserved"] if budget else 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "usage_reported_turns": usage_reported, "usage_total_turns": len(turns),
            "usage_complete": bool(turns) and usage_reported == len(turns),
            "model": MODEL, "cli": CLI, "reasoning_effort": "low"}


def _write_private(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _trial_order() -> list[tuple[str, str]]:
    order_rng = random.Random(SEED ^ 0x6A09E667)
    ordered: list[tuple[str, str]] = []
    for index in range(30):
        arms = list(ARMS)
        order_rng.shuffle(arms)
        ordered.extend((f"task-{index:02d}", arm) for arm in arms)
    return ordered


def _dataset(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"study": STUDY, "seed": SEED, "model": MODEL, "cli": CLI,
            "arms": list(ARMS), "records": records,
            "retained_content": "answer-free counts and verdicts only"}


def _audit_turn_counts(database: Path, run_id: str) -> tuple[int, int]:
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT turns_reserved FROM agent_run_turn_budgets WHERE run_id=?",
                         (run_id,)).fetchone()
        observed = db.execute(
            "SELECT COUNT(*) FROM agent_job_log l JOIN agent_jobs j USING(assignment_id) "
            "WHERE j.run_id=? AND l.event='codex_turn'", (run_id,)).fetchone()[0]
    if row is None:
        raise ValueError("completed arm has no durable model-call budget")
    return row[0], observed


def _validate_checkpoint(manifest: dict[str, Any], scheduler: AgentScheduler) -> list[dict[str, Any]]:
    if manifest.get("study") != STUDY or manifest.get("seed") != SEED or manifest.get("active") is not None:
        raise ValueError("checkpoint identity mismatch or interrupted arm; manual audit required")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) > 60:
        raise ValueError("invalid checkpoint record list")
    if [(row.get("case"), row.get("arm")) for row in records] != _trial_order()[:len(records)]:
        raise ValueError("checkpoint trial order differs from frozen order")
    if OUTPUT.exists() and json.loads(OUTPUT.read_text(encoding="utf-8")) != _dataset(records):
        raise ValueError("retained output differs from private checkpoint")
    with sqlite3.connect(scheduler.database) as db:
        durable_runs = {item[0] for item in db.execute(
            "SELECT run_id FROM agent_run_turn_budgets").fetchall()}
    if durable_runs != {row.get("run_id") for row in records}:
        raise ValueError("durable scheduler contains unrecorded or missing run")
    for row in records:
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("completed arm has no run id")
        budget = scheduler.model_turn_budget(run_id)
        if budget is None or budget["reserved"] != row.get("calls_reserved"):
            raise ValueError("checkpoint call accounting differs from durable scheduler")
        reserved, observed = _audit_turn_counts(scheduler.database, run_id)
        if reserved != row.get("calls_reserved") or observed != row.get("calls_observed"):
            raise ValueError("checkpoint observed call log differs from durable scheduler")
        jobs = scheduler.jobs(run_id)
        if sorted(job["state"] for job in jobs) != sorted(row.get("job_states", [])):
            raise ValueError("checkpoint jobs differ from durable scheduler")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the preregistered real-model study")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing real-model execution without --execute and prior review")
    runner = PinnedCodexCLI()
    if (version := runner.check()) != CLI:
        raise SystemExit(f"Codex CLI version mismatch: {version}")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_mode = STATE.lstat().st_mode
    if not stat.S_ISDIR(state_mode) or state_mode & 0o077:
        raise SystemExit("private checkpoint directory is not a private real directory")
    with (STATE / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_path = STATE / "checkpoint.json"
        if not manifest_path.exists() and OUTPUT.exists():
            raise SystemExit("retained output exists without private checkpoint; manual audit required")
        session = CodexSession(STATE / "metis.sqlite")
        scheduler = AgentScheduler(session.database, BridgeHost(max_parallel=1))
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = _validate_checkpoint(manifest, scheduler)
        else:
            records = []
            manifest = {"study": STUDY, "seed": SEED, "active": None, "records": records}
            _write_private(manifest_path, manifest)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        if not OUTPUT.exists() and records:
            _write_private(OUTPUT, _dataset(records))
            print("restored answer-free output from validated private checkpoint", flush=True)
        for case_id, arm in _trial_order()[len(records):]:
            manifest["active"] = {"case": case_id, "arm": arm}
            _write_private(manifest_path, manifest)
            index = int(case_id.rsplit("-", 1)[1])
            task, answer = make_task(SEED + index, size=20)
            row = run_arm(session, scheduler, runner, STATE, case_id, task, answer, arm)
            records.append(row)
            manifest["records"] = records
            manifest["active"] = None
            _write_private(manifest_path, manifest)
            _write_private(OUTPUT, _dataset(records))
            print(json.dumps({"case": case_id, "arm": arm, "completed_records": len(records)}), flush=True)


if __name__ == "__main__":
    main()
