"""Bounded Daybreak-side driver for scheduler waves.

Existing running attempts belong to an unknown driver after restart and are never
started a second time. The operator must reconcile them before resuming.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from metis.core.agent_scheduler import MAX_ATTEMPTS, AgentScheduler
from metis.core.codex_specialist import CodexRunner, run_assignment
from metis.core.run_lock import run_lock


def autopilot(scheduler: AgentScheduler, run_id: str, runner: CodexRunner, *, max_waves: int,
              drive: Callable[..., dict[str, Any]] = run_assignment,
              continuations: list[dict[str, str]] | None = None) -> dict[str, Any]:
    lock_id = "autopilot-" + hashlib.sha256(run_id.encode()).hexdigest()
    with run_lock(scheduler.database, lock_id, timeout=0):
        return _autopilot(scheduler, run_id, runner, max_waves=max_waves, drive=drive, continuations=continuations)


def _autopilot(scheduler: AgentScheduler, run_id: str, runner: CodexRunner, *, max_waves: int,
               drive: Callable[..., dict[str, Any]], continuations: list[dict[str, str]] | None) -> dict[str, Any]:
    if not 1 <= max_waves <= 10:
        raise ValueError("max-waves must be 1..10")
    continuations = continuations or []
    if len(continuations) > 10 or any(set(c) != {"wave_id", "report_id", "reason"}
                                      or not all(isinstance(v, str) for v in c.values())
                                      for c in continuations):
        raise ValueError("continuations must be a bounded list of wave_id, report_id, reason objects")
    context = scheduler.session.context(run_id)
    result: dict[str, Any] = {"run_id": run_id, "waves": [], "stop": ""}
    if context["status"] == "solved":
        result["stop"] = "already_solved"
        return result
    if any(c["state"] == "pending" for c in scheduler.candidates(run_id)):
        result["stop"] = "candidate_for_daybreak"
        return result
    with sqlite3.connect(scheduler.database) as db:
        row = db.execute("SELECT plan FROM ctf_agent_waves WHERE run_id=? ORDER BY created DESC LIMIT 1",
                         (run_id,)).fetchone()
    plan = json.loads(row[0]) if row else scheduler.ledger.create_wave(run_id)
    for _ in range(max_waves):
        wave_id = plan["wave_id"]
        if plan.get("execution_mode") == "sequential" or not plan["assignments"]:
            result["stop"] = "sequential_work_for_daybreak"
            break
        if any(j["wave_id"] != wave_id and j["state"] in {"queued", "running", "unknown"}
               for j in scheduler.jobs(run_id)):
            result["stop"] = "other_wave_needs_reconciliation"
            break
        scheduler.enqueue(run_id, wave_id)
        jobs = scheduler.jobs(run_id, wave_id)
        if any(j["state"] in {"running", "unknown"} for j in jobs):
            result["stop"] = "existing_attempt_needs_reconciliation"
            break
        while True:
            if any(c["state"] == "pending" for c in scheduler.candidates(run_id)):
                result["stop"] = "candidate_for_daybreak"
                break
            jobs = scheduler.jobs(run_id, wave_id)
            # Only a failure to start the host is automatically retryable. Other failures
            # can require a different hypothesis, authorization, or human intervention.
            for job in jobs:
                if (job["state"] == "failed" and (job["failure"] or "").startswith("spawn_error:")
                        and job["attempt_no"] < MAX_ATTEMPTS):
                    scheduler.retry(job["assignment_id"])
            jobs = scheduler.jobs(run_id, wave_id)
            if not any(j["state"] == "queued" for j in jobs):
                break
            started = scheduler.dispatch(run_id)["started"]
            if not started:
                # Spawn failures consume attempts, whereas slots occupied by other runs
                # require external progress and must not cause an unbounded poll.
                if any(j["state"] == "failed" and (j["failure"] or "").startswith("spawn_error:")
                       and j["attempt_no"] < MAX_ATTEMPTS for j in scheduler.jobs(run_id, wave_id)):
                    continue
                result["stop"] = "slots_unavailable_or_spawn_failed"
                break
            with ThreadPoolExecutor(max_workers=len(started)) as pool:
                futures = [pool.submit(drive, scheduler, run_id, j["assignment_id"], j["attempt_id"], runner)
                           for j in started]
                for future in futures:
                    future.result()
        synthesis = scheduler.ledger.synthesize(run_id, wave_id)
        result["waves"].append(synthesis)
        if result["stop"]:
            break
        if any(c["state"] == "pending" for c in scheduler.candidates(run_id)):
            result["stop"] = "candidate_for_daybreak"
        elif synthesis["decision"]["ended_without_report"]:
            result["stop"] = "failed_attempt_for_daybreak"
        elif not synthesis["decision"]["ready_for_synthesis"]:
            result["stop"] = "unresolved_attempts"
        elif not synthesis["decision"]["new_wave"]["allowed"]:
            result["stop"] = "synthesis_for_daybreak"
        elif len(result["waves"]) >= max_waves:
            result["stop"] = "wave_limit"
        else:
            choices = [c for c in continuations if c["wave_id"] == wave_id]
            if len(choices) != 1:
                result["stop"] = "continuation_for_daybreak"
                break
            choice = choices[0]
            report = next((r for r in synthesis["reports"] if r["report_id"] == choice["report_id"]), None)
            with sqlite3.connect(scheduler.database) as db:
                earlier = [json.loads(row[0]).get("reason", "") for row in db.execute(
                    "SELECT plan FROM ctf_agent_waves WHERE run_id=?", (run_id,))]
            reason = choice["reason"].strip()
            if (not report or report["status"] != "inconclusive" or reason != report["next_action"].strip()
                    or len(reason) < 10 or reason.casefold() in {r.casefold() for r in earlier}):
                result["stop"] = "invalid_or_repeated_continuation"
                break
            plan = scheduler.ledger.create_wave(run_id, reason=reason)
            continue
        break
    return result
