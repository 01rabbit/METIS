"""Scheduler for specialist assignments (Issue #11, P3/P4).

* Slots: ``min(host free slots, global slots, per-run slots, wave size)``; jobs that do
  not fit stay ``queued`` (slots are never faked).
* Jobs: ``queued -> running -> completed | failed | cancelled | timed_out`` plus
  ``unknown`` when a stop could not be confirmed (keeps its slot until released).
* Attempts: every (re)start gets a new attempt id; reports or intents from an older
  attempt are rejected and logged.
* Deadlines and max turns are enforced by ``tick()`` and by ``intent()``.
* The controller is the run's single writer: specialists send *tool intents*; the
  controller reserves turns and identities under the run lock, executes within a
  cancellable per-run operation lock, then revalidates the attempt before committing
  evidence. Submission, scope, credentials and delegation are not intents.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from metis.core.agent_contracts import PROFILES, Contract, select_model
from metis.core.agent_host import AgentHost
from metis.core.codex_session import CodexSession
from metis.core.contracts import RunStatus
from metis.core.ctf_orchestration import AgentLedger, assigned_artifact_scope
from metis.core.intent_identity import intent_identity
from metis.core.run_lock import run_lock
from metis.core.runtime import ToolRequest

MAX_ATTEMPTS = 3
LEASE_GRACE = 120
# An identical (canonical) action may run once more per run, and only on new evidence.
MAX_RETESTS = 1
# Executions of one canonical action across all attempts of a run (replays for stateless specialists).
RUN_REPLAY_LIMIT = 8
VIEWABLE = {"JPEG", "PNG", "GIF", "WEBP"}
MAX_CANDIDATES = 3
# Option variants of one tool on one artifact per attempt before the specialist must change approach.
FAMILY_LIMIT = 3
FORBIDDEN_INTENTS = {"submit": "official submission", "attest": "official submission", "grant": "scope expansion",
                     "auth": "credential handling", "remote": "network access", "web": "network access",
                     "sandbox": "dynamic execution", "delegate": "re-delegation", "extend": "budget increase"}


class ToolIntent(Contract):
    kind: Literal["data", "artifact", "derive", "view"]
    tool: str = Field(min_length=1, max_length=40)
    data: str | None = Field(default=None, max_length=65_536)
    artifact: str | None = Field(default=None, max_length=200)
    options: dict[str, Any] = Field(default_factory=dict)
    # Re-running an identical action is allowed only on newer evidence.
    new_evidence: list[int] = Field(default_factory=list, max_length=20)

    def identity(self) -> str:
        body = {"kind": self.kind, "tool": self.tool, "artifact": self.artifact,
                "options": self.options,
                "data_sha256": hashlib.sha256((self.data or "").encode()).hexdigest()}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class AgentScheduler:
    def __init__(self, database: Path, host: AgentHost):
        self.database = database
        self.host = host
        self.session = CodexSession(database)
        self.ledger = AgentLedger(database)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS agent_jobs (
                assignment_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, wave_id TEXT NOT NULL,
                role TEXT NOT NULL, state TEXT NOT NULL, attempt_id TEXT, attempt_no INTEGER NOT NULL DEFAULT 0,
                host TEXT, host_job_id TEXT, lease_until REAL, deadline REAL, deadline_seconds INTEGER NOT NULL,
                max_turns INTEGER NOT NULL, turns_used INTEGER NOT NULL DEFAULT 0, started REAL, finished REAL,
                failure TEXT, model TEXT, usage TEXT, created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_job_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, assignment_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                event TEXT NOT NULL, detail TEXT, time REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_actions (
                run_id TEXT NOT NULL, identity TEXT NOT NULL, assignment_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL, ok INTEGER NOT NULL, time REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_action_reservations (
                action_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, identity TEXT NOT NULL,
                assignment_id TEXT NOT NULL, attempt_id TEXT NOT NULL, family TEXT, created REAL NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS agent_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_run_turn_budgets (
                run_id TEXT PRIMARY KEY, turn_limit INTEGER NOT NULL, turns_reserved INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_turn_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL, reserved REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS agent_candidates (
                candidate_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL, digest TEXT NOT NULL, basis TEXT NOT NULL, path TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(agent_actions)")}
            if "family" not in columns:  # added after Issue #11 E2E; old rows keep NULL
                db.execute("ALTER TABLE agent_actions ADD COLUMN family TEXT")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database, timeout=30)

    # -- configuration -------------------------------------------------------------
    def config(self) -> dict[str, Any]:
        with self._db() as db:
            stored = {key: json.loads(value) for key, value in db.execute("SELECT key, value FROM agent_config")}
        return {"global_slots": stored.get("global_slots", 4), "per_run_slots": stored.get("per_run_slots", 2),
                "specialist_turn_budget": stored.get("specialist_turn_budget", 24),
                "catalog": stored.get("catalog", []), "current_model": stored.get("current_model"),
                "memory_retrieval": stored.get("memory_retrieval", True),
                "host": self.host.capabilities().model_dump()}

    def configure(self, *, global_slots: int | None = None, per_run_slots: int | None = None,
                  catalog: list[dict[str, Any]] | None = None, current_model: str | None = None,
                  memory_retrieval: bool | None = None, specialist_turn_budget: int | None = None) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if global_slots is not None:
            if not 1 <= global_slots <= 16:
                raise ValueError("global slots must be 1..16")
            changes["global_slots"] = global_slots
        if per_run_slots is not None:
            if not 1 <= per_run_slots <= 4:
                raise ValueError("per-run slots must be 1..4")
            changes["per_run_slots"] = per_run_slots
        if specialist_turn_budget is not None:
            if not 1 <= specialist_turn_budget <= 256:
                raise ValueError("specialist turn budget must be 1..256")
            changes["specialist_turn_budget"] = specialist_turn_budget
        if catalog is not None:
            if len(catalog) > 32 or any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
                                        or item.get("tier") not in {"lower", "standard", "strong"}
                                        or len(item["id"]) > 120 for item in catalog):
                raise ValueError("catalog entries are {id, tier: lower|standard|strong} reported by the host")
            changes["catalog"] = catalog
        if current_model is not None:
            changes["current_model"] = current_model[:120] or None
        if memory_retrieval is not None:
            changes["memory_retrieval"] = bool(memory_retrieval)
        with self._db() as db:
            for key, value in changes.items():
                db.execute("INSERT INTO agent_config(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
                           "value=excluded.value", (key, json.dumps(value)))
        return self.config()

    # -- jobs ------------------------------------------------------------------------------
    def enqueue(self, run_id: str, wave_id: str) -> list[dict[str, Any]]:
        plan = self.ledger._plan(run_id, wave_id)
        now = time.time()
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO agent_run_turn_budgets(run_id,turn_limit,turns_reserved,created) "
                       "VALUES (?,?,0,?)", (run_id, self.config()["specialist_turn_budget"], now))
            for item in plan["assignments"]:
                db.execute("INSERT OR IGNORE INTO agent_jobs(assignment_id,run_id,wave_id,role,state,"
                           "deadline_seconds,max_turns,created) VALUES (?,?,?,?,?,?,?,?)",
                           (item["assignment_id"], run_id, wave_id, item["role"], "queued",
                            int(item.get("deadline_seconds", 600)), int(item.get("max_turns", 6)), now))
        return self.jobs(run_id, wave_id)

    def reserve_model_turn(self, run_id: str, assignment_id: str, attempt_id: str) -> dict[str, Any] | None:
        """Atomically reserve one Codex call attempt from the run's immutable turn budget.

        Reservations are charged before the provider call and never refunded on failure or retry.
        ``None`` means the cap is exhausted; the active assignment is ended and logged.
        """
        db = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT run_id,state,attempt_id,deadline FROM agent_jobs WHERE assignment_id=?",
                             (assignment_id,)).fetchone()
            if row is None or row[:3] != (run_id, "running", attempt_id):
                db.execute("ROLLBACK")
                raise ValueError("attempt is not the running attempt of this run")
            if row[3] and time.time() > row[3]:
                now = time.time()
                db.execute("UPDATE agent_jobs SET state='timed_out',failure=?,finished=? WHERE assignment_id=? "
                           "AND attempt_id=?", ("deadline exceeded before model-turn reservation", now,
                                                 assignment_id, attempt_id))
                self._log(db, assignment_id, attempt_id, "model_turn_deadline_expired")
                db.execute("COMMIT")
                raise ValueError("assignment deadline exceeded before model-turn reservation")
            budget = db.execute("SELECT turn_limit,turns_reserved FROM agent_run_turn_budgets WHERE run_id=?",
                                (run_id,)).fetchone()
            if budget is None:
                db.execute("ROLLBACK")
                raise ValueError("run specialist-turn budget is not initialized; enqueue the wave first")
            limit, used = budget
            if used >= limit:
                now = time.time()
                db.execute("UPDATE agent_jobs SET state='failed',failure=?,finished=? WHERE assignment_id=? "
                           "AND attempt_id=?", ("run specialist model-turn budget exhausted", now,
                                                 assignment_id, attempt_id))
                self._log(db, assignment_id, attempt_id, "model_turn_budget_exhausted", f"{used}/{limit}")
                db.execute("COMMIT")
                return None
            now = time.time()
            turn_no = used + 1
            db.execute("UPDATE agent_run_turn_budgets SET turns_reserved=? WHERE run_id=?", (turn_no, run_id))
            db.execute("INSERT INTO agent_turn_reservations(run_id,assignment_id,attempt_id,reserved) "
                       "VALUES (?,?,?,?)", (run_id, assignment_id, attempt_id, now))
            self._log(db, assignment_id, attempt_id, "model_turn_reserved", f"{turn_no}/{limit}")
            db.execute("COMMIT")
            return {"turn": turn_no, "limit": limit, "remaining": limit - turn_no}
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def model_turn_budget(self, run_id: str) -> dict[str, int] | None:
        with self._db() as db:
            row = db.execute("SELECT turn_limit,turns_reserved FROM agent_run_turn_budgets WHERE run_id=?",
                             (run_id,)).fetchone()
        return None if row is None else {"limit": row[0], "reserved": row[1], "remaining": row[0] - row[1]}

    def jobs(self, run_id: str | None = None, wave_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_jobs WHERE 1=1"
        values: list[str] = []
        if run_id:
            query, values = query + " AND run_id=?", [*values, run_id]
        if wave_id:
            query, values = query + " AND wave_id=?", [*values, wave_id]
        with self._db() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute(query + " ORDER BY created, assignment_id", values)]
        for row in rows:
            row["model"] = json.loads(row["model"]) if row["model"] else None
            row["usage"] = json.loads(row["usage"]) if row["usage"] else {"tokens": "unknown", "cost": "unknown"}
        return rows

    def _log(self, db: sqlite3.Connection, assignment_id: str, attempt_id: str | None, event: str,
             detail: str = "") -> None:
        db.execute("INSERT INTO agent_job_log(assignment_id,attempt_id,event,detail,time) VALUES (?,?,?,?,?)",
                   (assignment_id, attempt_id or "-", event, detail[:300], time.time()))

    def dispatch(self, run_id: str | None = None) -> dict[str, Any]:
        """Start as many queued jobs as the slots allow (atomic slot reservation)."""
        self.tick()
        settings = self.config()
        capability = self.host.capabilities()
        limit = min(settings["global_slots"], capability.max_parallel)
        now = time.time()
        with self._db() as read_db:
            queued_runs = {row[0] for row in read_db.execute(
                "SELECT DISTINCT run_id FROM agent_jobs WHERE state='queued'" +
                (" AND run_id=?" if run_id else ""), [run_id] if run_id else [])}
        run_seconds = {identity: self.session.context(identity)["seconds_remaining"]
                       for identity in queued_runs}
        reserved: list[dict[str, Any]] = []
        db = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            busy = [dict(row) for row in db.execute("SELECT run_id FROM agent_jobs WHERE state IN "
                                                     "('running','unknown')")]
            per_run: dict[str, int] = {}
            for row in busy:
                per_run[row["run_id"]] = per_run.get(row["run_id"], 0) + 1
            free = limit - len(busy)
            query = "SELECT * FROM agent_jobs WHERE state='queued'" + (" AND run_id=?" if run_id else "")
            for row in db.execute(query + " ORDER BY created, assignment_id", [run_id] if run_id else []):
                if free <= 0:
                    break
                if per_run.get(row["run_id"], 0) >= settings["per_run_slots"]:
                    continue
                shared_seconds = run_seconds.get(row["run_id"], 0)
                deadline_seconds = min(row["deadline_seconds"], shared_seconds)
                if deadline_seconds <= 0:
                    db.execute("UPDATE agent_jobs SET state='timed_out', failure=?, finished=? "
                               "WHERE assignment_id=? AND state='queued'",
                               ("run wall-clock budget exhausted", now, row["assignment_id"]))
                    self._log(db, row["assignment_id"], None, "run_deadline_expired")
                    continue
                attempt = uuid4().hex[:16]
                db.execute("UPDATE agent_jobs SET state='running', attempt_id=?, attempt_no=attempt_no+1, host=?, "
                           "started=?, deadline=?, lease_until=?, deadline_seconds=?, turns_used=0, "
                           "failure=NULL, finished=NULL "
                           "WHERE assignment_id=? AND state='queued'",
                           (attempt, self.host.name, now, now + deadline_seconds,
                            now + deadline_seconds + LEASE_GRACE, deadline_seconds, row["assignment_id"]))
                self._log(db, row["assignment_id"], attempt, "started")
                per_run[row["run_id"]] = per_run.get(row["run_id"], 0) + 1
                free -= 1
                reserved.append({**dict(row), "deadline_seconds": deadline_seconds,
                                 "attempt_id": attempt})
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        started = []
        for job in reserved:
            plan = self.ledger._plan(job["run_id"], job["wave_id"])
            assignment = next(item for item in plan["assignments"] if item["assignment_id"] == job["assignment_id"])
            assignment["deadline_seconds"] = job["deadline_seconds"]
            model = select_model(PROFILES[job["role"]].tier, settings["catalog"], current=settings["current_model"])
            brief = self.brief(job["run_id"], assignment, job["attempt_id"])
            try:
                host_job = self.host.spawn(assignment, brief, model)
            except Exception as exc:  # noqa: BLE001 -- any host failure releases the slot
                with self._db() as db:
                    db.execute("UPDATE agent_jobs SET state='failed', failure=?, finished=? WHERE assignment_id=? "
                               "AND attempt_id=?", (f"spawn_error: {type(exc).__name__}", time.time(),
                                                    job["assignment_id"], job["attempt_id"]))
                    self._log(db, job["assignment_id"], job["attempt_id"], "spawn_failed", type(exc).__name__)
                continue
            with self._db() as db:
                db.execute("UPDATE agent_jobs SET host_job_id=?, model=? WHERE assignment_id=? AND attempt_id=?",
                           (host_job, model.model_dump_json(), job["assignment_id"], job["attempt_id"]))
            started.append({"assignment_id": job["assignment_id"], "attempt_id": job["attempt_id"],
                            "host_job_id": host_job, "model": model.model_dump(), "brief": brief})
        queued = sum(1 for job in self.jobs(run_id) if job["state"] == "queued")
        return {"started": started, "queued": queued, "slot_limit": limit,
                "per_run_slots": settings["per_run_slots"], "host": self.host.name}

    def brief(self, run_id: str, assignment: dict[str, Any], attempt_id: str) -> dict[str, Any]:
        """Minimal no-history brief (spec 5.1): only references, never raw data or candidates."""
        context = self.session.context(run_id)
        declared_artifacts = context["challenge"].get("artifacts", [])[:32]
        artifact_scope = assigned_artifact_scope(assignment, set(declared_artifacts))
        visible_artifacts = (declared_artifacts if artifact_scope is None
                             else [name for name in declared_artifacts if name in artifact_scope])
        prior_knowledge: list[dict[str, Any]] = []
        if self.config()["memory_retrieval"]:
            from metis.core.ctf_knowledge import KnowledgeBase

            challenge = context["challenge"]
            categories = challenge.get("categories", [])
            query = " ".join([challenge.get("title", ""), *[str(item) for item in categories],
                              challenge.get("description", "")[:512]])
            prior_knowledge = KnowledgeBase(self.database).search_for_run(
                run_id, query, category=str(categories[0]) if categories else None, limit=3,
            )
        observations = [event.sequence for event in self.session.store.read(run_id)
                        if event.status == RunStatus.OBSERVING][-10:]
        with self._db() as db:
            hypotheses = []
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='ctf_hypotheses'").fetchone():
                hypotheses = [{"status": status, "summary": summary} for status, summary in db.execute(
                    "SELECT status, summary FROM ctf_hypotheses WHERE run_id=? ORDER BY created DESC LIMIT 5",
                    (run_id,))]
            prior_reports = [{key: (str(value)[:300] if isinstance(value, str) else value)
                              for key, value in json.loads(row[0]).items()
                              if key in {"hypothesis", "next_action", "status", "event_sequences"}}
                             for row in db.execute("SELECT payload FROM ctf_agent_reports WHERE run_id=? "
                                                   "ORDER BY created DESC LIMIT 4", (run_id,))]
            rejected = [json.loads(row[0])["next_action"] for row in db.execute(
                "SELECT payload FROM ctf_agent_reports WHERE run_id=? ORDER BY created DESC LIMIT 20", (run_id,))
                if json.loads(row[0])["status"] == "rejected"][:5]
        profile = PROFILES[assignment["role"]]
        prefix = f"--attempt {attempt_id}"
        turn_budget = self.model_turn_budget(run_id)
        return {
            "run_id": run_id, "wave_id": assignment["assignment_id"].split(":")[0],
            "assignment_id": assignment["assignment_id"], "attempt_id": attempt_id, "role": assignment["role"],
            "objective": assignment["objective"], "deliverable": assignment["deliverable"],
            "evidence_required": profile.evidence_required,
            "artifacts": visible_artifacts,
            "evidence_refs": observations, "hypotheses": hypotheses, "rejected_actions": rejected,
            "prior_reports": prior_reports,
            "prior_knowledge": prior_knowledge,
            "tools": profile.recommended_tools, "max_turns": assignment.get("max_turns", profile.max_turns),
            "run_model_turn_budget": turn_budget,
            "seconds": assignment.get("deadline_seconds"), "max_output_chars": 8000,
            "forbidden": ["official submission", "scope or endpoint grants", "credentials", "re-delegation",
                          "running challenge programs on the host", "putting candidates in reports"],
            "how": {
                "tool": f"metis agent intent {run_id} {assignment['assignment_id']} {prefix} --file INTENT.json",
                "report": f"metis agent complete {run_id} {assignment['assignment_id']} {prefix} --file REPORT.json",
                "give_up": f"metis agent fail {run_id} {assignment['assignment_id']} {prefix} --reason TEXT",
                "candidate": "never in reports; tell Daybreak which recorded transformation produces it",
            },
        }

    def _running(self, assignment_id: str, attempt_id: str) -> dict[str, Any]:
        rows = [job for job in self.jobs() if job["assignment_id"] == assignment_id]
        if not rows:
            raise ValueError("unknown assignment")
        job = rows[0]
        if job["attempt_id"] != attempt_id or job["state"] != "running":
            with self._db() as db:
                self._log(db, assignment_id, attempt_id, "rejected_stale",
                          f"current={job['attempt_id']} state={job['state']}")
            raise ValueError("stale or unknown attempt; rejected")
        return job

    def _assignment_artifact_scope(self, job: dict[str, Any]) -> set[str] | None:
        """Return the explicit artifact capability for a job; ``None`` means run-wide access."""
        plan = self.ledger._plan(job["run_id"], job["wave_id"])
        assignment = next((item for item in plan["assignments"]
                           if item.get("assignment_id") == job["assignment_id"]), None)
        if assignment is None:
            raise ValueError("assignment is not in its wave plan")
        declared = set(self.session.context(job["run_id"])["challenge"].get("artifacts", []))
        return assigned_artifact_scope(assignment, declared)

    def _register_derived_artifact(self, job: dict[str, Any], artifact: str) -> None:
        """Extend only the producing assignment's explicit scope with its derived output."""
        plan = self.ledger._plan(job["run_id"], job["wave_id"])
        assignment = next(item for item in plan["assignments"]
                          if item.get("assignment_id") == job["assignment_id"])
        declared = set(self.session.context(job["run_id"])["challenge"].get("artifacts", []))
        allowed = assigned_artifact_scope(assignment, declared)
        if allowed is None:
            return  # No explicit subset: the run-wide scope already includes derived files.
        if artifact not in declared:
            raise ValueError("derived artifact is not registered in the run")
        if artifact in allowed:
            return
        inputs = assignment["inputs"]
        inputs["artifacts"] = [*inputs["artifacts"], artifact]
        with self._db() as db:
            db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                       (json.dumps(plan, sort_keys=True), job["wave_id"]))
            self._log(db, job["assignment_id"], job["attempt_id"], "derived_scope_extended",
                      "own derived artifact")

    def complete(self, run_id: str, assignment_id: str, attempt_id: str, report: dict[str, Any]) -> dict[str, Any]:
        with run_lock(self.database, run_id):
            job = self._running(assignment_id, attempt_id)
            if job["run_id"] != run_id:
                raise ValueError("assignment belongs to another run")
            if job["deadline"] and time.time() > job["deadline"]:
                self._stop(job)
                self.session.cancel_active_operation(run_id, assignment_id, attempt_id)
                self._end(assignment_id, attempt_id, "timed_out", "deadline exceeded before report")
                raise ValueError("assignment deadline exceeded before report")
            with self._db() as db:
                pending = db.execute("SELECT 1 FROM agent_action_reservations WHERE assignment_id=? AND attempt_id=?",
                                     (assignment_id, attempt_id)).fetchone()
            if pending:
                raise ValueError("cannot complete while a controller intent is still in flight")
            if len(json.dumps(report)) > 8000 + 2000:
                raise ValueError("report exceeds the output limit")
            stored = self.ledger.record_report(run_id, job["wave_id"], assignment_id, report,
                                               attempt_id=attempt_id)
            with self._db() as db:
                db.execute("UPDATE agent_jobs SET state='completed', finished=? WHERE assignment_id=? AND attempt_id=?",
                           (time.time(), assignment_id, attempt_id))
                self._log(db, assignment_id, attempt_id, "completed")
            return {**stored, "state": "completed"}

    def fail(self, assignment_id: str, attempt_id: str, reason: str) -> dict[str, Any]:
        job = self._running(assignment_id, attempt_id)
        with run_lock(self.database, job["run_id"]):
            current = self._running(assignment_id, attempt_id)
            self.session.cancel_active_operation(current["run_id"], assignment_id, attempt_id)
            return self._end(assignment_id, attempt_id, "failed", reason[:300] or "failed")

    def _end(self, assignment_id: str, attempt_id: str, state: str, failure: str) -> dict[str, Any]:
        target = next((job for job in self.jobs() if job["assignment_id"] == assignment_id), None)
        if target is None:
            raise ValueError("unknown assignment")
        with run_lock(self.database, target["run_id"]), self._db() as db:
            db.execute("UPDATE agent_jobs SET state=?, failure=?, finished=? WHERE assignment_id=? AND attempt_id=?",
                       (state, failure, time.time(), assignment_id, attempt_id))
            db.execute("DELETE FROM agent_action_reservations WHERE assignment_id=? AND attempt_id=?",
                       (assignment_id, attempt_id))
            self._log(db, assignment_id, attempt_id, state, failure)
        return {"assignment_id": assignment_id, "attempt_id": attempt_id, "state": state, "reason": failure}

    def cancel(self, *, assignment_id: str | None = None, wave_id: str | None = None,
               reason: str = "cancelled by Daybreak") -> list[dict[str, Any]]:
        target_runs = sorted({job["run_id"] for job in self.jobs() if
                              (assignment_id and job["assignment_id"] == assignment_id)
                              or (wave_id and job["wave_id"] == wave_id)})
        results = []
        for run_id in target_runs:
            with run_lock(self.database, run_id):
                targets = [job for job in self.jobs(run_id) if (assignment_id and
                           job["assignment_id"] == assignment_id) or (wave_id and job["wave_id"] == wave_id)]
                for job in targets:
                    if job["state"] == "queued":
                        with self._db() as db:
                            db.execute("UPDATE agent_jobs SET state='cancelled', failure=?, finished=? WHERE assignment_id=? "
                                       "AND state='queued'", (reason, time.time(), job["assignment_id"]))
                        results.append({"assignment_id": job["assignment_id"], "state": "cancelled"})
                    elif job["state"] == "running":
                        confirmed = self._stop(job)
                        self.session.cancel_active_operation(run_id, job["assignment_id"], job["attempt_id"])
                        results.append(self._end(job["assignment_id"], job["attempt_id"],
                                                 "cancelled" if confirmed else "unknown",
                                                 reason if confirmed else reason + " (stop not confirmed)"))
        return results

    def _stop(self, job: dict[str, Any]) -> bool:
        try:
            return bool(job["host_job_id"]) and self.host.cancel(job["host_job_id"])
        except Exception:  # noqa: BLE001 -- an unconfirmed stop is reported as unknown
            return False

    def release(self, assignment_id: str) -> dict[str, Any]:
        """Operator confirms an ``unknown`` job is stopped; its slot becomes free."""
        job = next((item for item in self.jobs() if item["assignment_id"] == assignment_id), None)
        if job is None or job["state"] != "unknown":
            raise ValueError("only unknown jobs can be released")
        return self._end(assignment_id, job["attempt_id"], "cancelled", "released after confirmed stop")

    def retry(self, assignment_id: str) -> dict[str, Any]:
        job = next((item for item in self.jobs() if item["assignment_id"] == assignment_id), None)
        if job is None or job["state"] not in {"failed", "timed_out", "cancelled"}:
            raise ValueError("only failed, timed-out or cancelled jobs can be retried")
        if job["attempt_no"] >= MAX_ATTEMPTS:
            raise ValueError("attempt limit reached; reassign or hand over to Daybreak")
        with self._db() as db:
            db.execute("UPDATE agent_jobs SET state='queued', failure=NULL WHERE assignment_id=?", (assignment_id,))
            self._log(db, assignment_id, job["attempt_id"], "requeued")
        return {"assignment_id": assignment_id, "state": "queued", "next_attempt": job["attempt_no"] + 1}

    def tick(self) -> list[dict[str, Any]]:
        """Enforce deadlines, collect finished host jobs and recover expired leases."""
        changes = []
        now = time.time()
        for job in self.jobs():
            if job["state"] != "running":
                continue
            if job["deadline"] and now > job["deadline"]:
                confirmed = self._stop(job)
                with run_lock(self.database, job["run_id"]):
                    current = next((item for item in self.jobs(job["run_id"])
                                    if item["assignment_id"] == job["assignment_id"]), None)
                    if current and current["attempt_id"] == job["attempt_id"] and current["state"] == "running":
                        self.session.cancel_active_operation(job["run_id"], job["assignment_id"], job["attempt_id"])
                        changes.append(self._end(job["assignment_id"], job["attempt_id"],
                                                 "timed_out" if confirmed else "unknown", "deadline exceeded"))
                continue
            if not job["host_job_id"]:
                continue
            try:
                status = self.host.poll(job["host_job_id"])
            except Exception:  # noqa: BLE001
                status = {"state": "unknown"}
            if status.get("usage"):
                with self._db() as db:
                    db.execute("UPDATE agent_jobs SET usage=? WHERE assignment_id=?",
                               (json.dumps(status["usage"]), job["assignment_id"]))
            if status["state"] == "finished":
                output = self.host.collect(job["host_job_id"])
                if output is None:
                    continue  # Bridge/sequential: the report arrives through `agent complete`.
                try:
                    changes.append(self.complete(job["run_id"], job["assignment_id"], job["attempt_id"], output))
                except ValueError as exc:
                    with run_lock(self.database, job["run_id"]):
                        self.session.cancel_active_operation(job["run_id"], job["assignment_id"],
                                                             job["attempt_id"])
                        changes.append(self._end(job["assignment_id"], job["attempt_id"], "failed",
                                                 f"invalid report: {str(exc)[:200]}"))
            elif status["state"] == "failed":
                with run_lock(self.database, job["run_id"]):
                    current = next((item for item in self.jobs(job["run_id"])
                                    if item["assignment_id"] == job["assignment_id"]), None)
                    if current and current["attempt_id"] == job["attempt_id"] and current["state"] == "running":
                        self.session.cancel_active_operation(job["run_id"], job["assignment_id"],
                                                             job["attempt_id"])
                        changes.append(self._end(job["assignment_id"], job["attempt_id"], "failed",
                                                 "host reported failure"))
            elif status["state"] == "unknown" and job["lease_until"] and now > job["lease_until"]:
                with run_lock(self.database, job["run_id"]):
                    current = next((item for item in self.jobs(job["run_id"])
                                    if item["assignment_id"] == job["assignment_id"]), None)
                    if current and current["attempt_id"] == job["attempt_id"] and current["state"] == "running":
                        self.session.cancel_active_operation(job["run_id"], job["assignment_id"],
                                                             job["attempt_id"])
                        changes.append(self._end(job["assignment_id"], job["attempt_id"], "unknown",
                                                 "lease expired"))
        return changes

    # -- controller-mediated tool use ---------------------------------------------------------
    def intent(self, run_id: str, assignment_id: str, attempt_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        kind = str(raw.get("kind", ""))
        if kind in FORBIDDEN_INTENTS:
            with self._db() as db:
                self._log(db, assignment_id, attempt_id, "intent_refused", kind)
            raise ValueError(f"{FORBIDDEN_INTENTS[kind]} is Daybreak-only; specialists cannot request it")
        try:
            intent = ToolIntent.model_validate(raw)
        except ValidationError:
            raise ValueError("intent must be {kind: data|artifact|derive, tool, data|artifact, options}") from None
        identity, family = intent_identity(intent.kind, intent.tool, intent.artifact, intent.options, intent.data,
                                           self.session.artifact_root(run_id))
        action_id = uuid4().hex
        with run_lock(self.database, run_id):
            job = self._running(assignment_id, attempt_id)
            if job["run_id"] != run_id:
                raise ValueError("assignment belongs to another run")
            if job["deadline"] and time.time() > job["deadline"]:
                self._stop(job)
                self._end(assignment_id, attempt_id, "timed_out", "deadline exceeded")
                raise ValueError("assignment deadline exceeded")
            if job["turns_used"] >= job["max_turns"]:
                self._stop(job)
                self._end(assignment_id, attempt_id, "timed_out", "max turns reached")
                raise ValueError("assignment max turns reached")
            if intent.kind in {"artifact", "derive", "view"}:
                allowed_artifacts = self._assignment_artifact_scope(job)
                if allowed_artifacts is not None and intent.artifact not in allowed_artifacts:
                    with self._db() as db:
                        self._log(db, assignment_id, attempt_id, "intent_scope_refused", "unassigned artifact")
                    raise ValueError("artifact is outside this assignment's scope")
            self._check_repeat(run_id, assignment_id, attempt_id, identity, family, intent.new_evidence)
            with self._db() as db:
                db.execute("INSERT INTO agent_action_reservations "
                           "(action_id,run_id,identity,assignment_id,attempt_id,family,created) "
                           "VALUES (?,?,?,?,?,?,?)", (action_id, run_id, identity, assignment_id,
                                                       attempt_id, family, time.time()))
                db.execute("UPDATE agent_jobs SET turns_used=turns_used+1 "
                           "WHERE assignment_id=? AND attempt_id=?", (assignment_id, attempt_id))
                self._log(db, assignment_id, attempt_id, "intent_started", action_id)
            turns_left = job["max_turns"] - job["turns_used"] - 1

        try:
            if intent.kind == "data":
                if intent.data is None:
                    raise ValueError("data intents need data")
                result = self.session.act(run_id, ToolRequest(tool=intent.tool, data=intent.data))
                ok = bool(result.get("ok"))
            elif intent.kind == "view":
                if not intent.artifact:
                    raise ValueError("view intents need an image artifact name")
                result = self.session.artifact(run_id, intent.artifact, "image", {},
                                               _owner=(assignment_id, attempt_id))
                details = result.get("result") or {}
                ok = bool(result.get("ok")) and str(details.get("format", "")).upper() in VIEWABLE
                result = {**result, "view": {"artifact": intent.artifact, "attached_next_turn": ok}}
                if not ok:
                    result["view"]["reason"] = "only registered JPEG/PNG/GIF/WebP images can be viewed"
            else:
                if not intent.artifact:
                    raise ValueError("artifact intents need an artifact name")
                if intent.kind == "artifact":
                    result = self.session.artifact(run_id, intent.artifact, intent.tool, intent.options,
                                                   _owner=(assignment_id, attempt_id))
                else:
                    result = self.session.derive(run_id, intent.artifact, intent.tool, intent.options,
                                                 _owner=(assignment_id, attempt_id), _defer_store=True)
                ok = bool(result.get("ok"))
        except BaseException:
            with run_lock(self.database, run_id), self._db() as db:
                db.execute("DELETE FROM agent_action_reservations WHERE action_id=?", (action_id,))
                self._log(db, assignment_id, attempt_id, "intent_failed", action_id)
            raise

        with run_lock(self.database, run_id):
            current = next((item for item in self.jobs(run_id)
                            if item["assignment_id"] == assignment_id), None)
            with self._db() as db:
                db.execute("DELETE FROM agent_action_reservations WHERE action_id=?", (action_id,))
            if current is None or current["attempt_id"] != attempt_id or current["state"] != "running":
                with self._db() as db:
                    self._log(db, assignment_id, attempt_id, "intent_result_discarded", action_id)
                raise ValueError("assignment ended while the intent was executing; result discarded")
            if current["deadline"] and time.time() > current["deadline"]:
                self._stop(current)
                self._end(assignment_id, attempt_id, "timed_out", "deadline exceeded during intent")
                raise ValueError("assignment deadline exceeded during intent")
            if result.get("cancelled") is True:
                with self._db() as db:
                    self._log(db, assignment_id, attempt_id, "intent_cancelled", action_id)
                raise ValueError("intent was cancelled; result discarded")
            sequence = result.pop("_evidence_sequence", None)
            events = self.session.store.read(run_id)
            if type(sequence) is not int or sequence < 0 or sequence >= len(events) \
                    or events[sequence].status != RunStatus.OBSERVING:
                with self._db() as db:
                    self._log(db, assignment_id, attempt_id, "intent_result_discarded", "no observation")
                raise ValueError("intent completed without an observation")
            if intent.kind == "derive" and result.get("ok") is True:
                encoded = result.pop("_derived_content", None)
                suffix = result.pop("_derived_suffix", None)
                if not isinstance(encoded, str) or not isinstance(suffix, str):
                    raise ValueError("derived operation returned no pending content")
                content = base64.b64decode(encoded, validate=True)
                artifact = self.session.store_artifact(run_id, content, suffix=suffix)
                self._register_derived_artifact(current, artifact)
                result["artifact"] = artifact
            with self._db() as db:
                db.execute("INSERT INTO agent_actions(run_id,identity,assignment_id,attempt_id,sequence,ok,time,"
                           "family) VALUES (?,?,?,?,?,?,?,?)", (run_id, identity, assignment_id, attempt_id,
                                                                sequence, int(ok), time.time(), family))
        return {"assignment_id": assignment_id, "attempt_id": attempt_id, "action_identity": identity,
                "evidence_sequence": sequence, "turns_left": turns_left, "observation": result}

    def _check_repeat(self, run_id: str, assignment_id: str, attempt_id: str, identity: str, family: str | None,
                      new_evidence: list[int]) -> None:
        """Duplicate and retry control on the canonical identity (caller holds the run lock).

        Specialists are stateless and cannot read each other's observations, so the duplicate
        scope is the attempt: an attempt may observe the result of an action another attempt
        already ran (a replay), but the same canonical action runs at most ``RUN_REPLAY_LIMIT``
        times per run.

        * Inside one attempt, an identical action is refused unless ``new_evidence`` cites an
          observation newer than its last run *and* from a different action; it may be re-tested
          at most ``MAX_RETESTS`` times.
        * One attempt may try at most ``FAMILY_LIMIT`` option variants of one tool on one artifact.
        Refusals are logged and name the earlier evidence.
        """
        events = self.session.store.read(run_id)
        known = {event.sequence for event in events}
        if not set(new_evidence) <= known:
            raise ValueError("new_evidence references unknown run events")
        observed = {event.sequence for event in events if event.status == RunStatus.OBSERVING}
        with self._db() as db:
            prior = db.execute("SELECT sequence, attempt_id FROM agent_actions WHERE run_id=? AND identity=? "
                               "ORDER BY sequence", (run_id, identity)).fetchall()
            pending = db.execute("SELECT identity FROM agent_action_reservations WHERE run_id=? AND identity=?",
                                 (run_id, identity)).fetchall()
            pending_variants = {row[0] for row in db.execute(
                "SELECT identity FROM agent_action_reservations WHERE attempt_id=? AND family=?",
                (attempt_id, family))} if family else set()
            completed_variants = {row[0] for row in db.execute(
                "SELECT DISTINCT identity FROM agent_actions WHERE attempt_id=? AND family=?",
                (attempt_id, family))} if family else set()
            variants = len(pending_variants | completed_variants)
        mine = [row for row in prior if row[1] == attempt_id]
        refusal: tuple[str, str, str] | None = (
            ("intent_duplicate", "identical action is in progress",
             "duplicate action: the same canonical request is already in progress") if pending else None)
        if refusal is None and mine:
            last = mine[-1][0]
            same = {row[0] for row in prior}
            fresh = [item for item in new_evidence if item > last and item in observed and item not in same]
            if len(mine) > MAX_RETESTS:
                refusal = ("intent_duplicate", f"retest limit; event {last}",
                           (f"duplicate action: you already observed this at event {last} and re-tested it; the "
                            "re-test limit is reached, change the approach"))
            elif not fresh:
                refusal = ("intent_duplicate", f"event {last}",
                           (f"duplicate action: you already ran the same canonical request at event {last}; use "
                            "that observation, or cite a newer observation from a different action in "
                            "new_evidence to re-test"))
        elif refusal is None and len(prior) + len(pending) >= RUN_REPLAY_LIMIT:
            refusal = ("intent_duplicate", f"run replay limit; event {prior[-1][0]}",
                       (f"duplicate action: this canonical request already ran {len(prior)} times in this run "
                        f"(last at event {prior[-1][0]}); use a different action"))
        elif refusal is None and family and variants >= FAMILY_LIMIT:
            refusal = ("intent_variant_limit", f"{variants} variants",
                       (f"variant limit: {variants} option variants of this tool on this artifact already ran in "
                        "this attempt; use a different tool or report what is known"))
        if refusal:
            with self._db() as db:  # committed before raising so the refusal stays in the audit log
                self._log(db, assignment_id, attempt_id, refusal[0], refusal[1])
            raise ValueError(refusal[2])

    # -- private candidate hand-off (spec 6.1: never in reports, only to Daybreak) -----------------
    def candidate_dir(self, run_id: str) -> Path:
        return self.database.parent / ".metis-candidates" / run_id

    def candidate(self, run_id: str, assignment_id: str, attempt_id: str, value: str,
                  basis: list[int]) -> dict[str, Any]:
        """Store a specialist's candidate privately (0600 file, digest in the DB, nothing in logs)."""
        job = self._running(assignment_id, attempt_id)
        if job["run_id"] != run_id:
            raise ValueError("assignment belongs to another run")
        if not 1 <= len(value) <= 512 or "\n" in value or "\r" in value:
            raise ValueError("a candidate is one line of 1..512 characters")
        known = {event.sequence for event in self.session.store.read(run_id)}
        if not basis or not set(basis) <= known or len(basis) > 20:
            raise ValueError("a candidate must cite the run events that produce it")
        with self._db() as db:
            count = db.execute("SELECT COUNT(*) FROM agent_candidates WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
            if count >= MAX_CANDIDATES:
                raise ValueError("candidate limit for this attempt reached")
            salt = db.execute("SELECT value FROM agent_config WHERE key='candidate_salt'").fetchone()
            if salt is None:
                salt_value = json.dumps(uuid4().hex + uuid4().hex)
                db.execute("INSERT INTO agent_config(key,value) VALUES ('candidate_salt',?)", (salt_value,))
                salt = (salt_value,)
        digest = hashlib.sha256((json.loads(salt[0]) + value).encode()).hexdigest()
        identity = "C" + uuid4().hex[:10]
        directory = self.candidate_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        path = directory / f"{identity}.txt"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
        with self._db() as db:
            db.execute("INSERT INTO agent_candidates VALUES (?,?,?,?,?,?,?,?,?)",
                       (identity, run_id, assignment_id, attempt_id, digest, json.dumps(sorted(set(basis))),
                        str(path), "pending", time.time()))
            self._log(db, assignment_id, attempt_id, "candidate_received", f"{identity} digest={digest[:12]}")
        return {"candidate_id": identity, "stored": "private", "digest": digest[:12]}

    def candidates(self, run_id: str, *, purge: str | None = None) -> list[dict[str, Any]]:
        """List candidates for Daybreak (paths and digests only). ``purge`` deletes one or 'all'."""
        with self._db() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM agent_candidates WHERE run_id=? ORDER BY created",
                                                     (run_id,))]
            for row in rows:
                if purge in {"all", row["candidate_id"]} and row["state"] != "purged":
                    Path(row["path"]).unlink(missing_ok=True)
                    db.execute("UPDATE agent_candidates SET state='purged' WHERE candidate_id=?", (row["candidate_id"],))
                    row["state"] = "purged"
        return [{"candidate_id": row["candidate_id"], "assignment_id": row["assignment_id"],
                 "basis_events": json.loads(row["basis"]), "digest": row["digest"][:12], "state": row["state"],
                 "candidate_file": row["path"] if row["state"] == "pending" else None} for row in rows]
