"""Bounded planner/executor wave specifications for AI subagents.

This module emits plans only; the selected AI remains the agent runtime and the
official verifier remains controller-owned.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from metis.core.codex_session import CodexSession
from metis.core.ctf_knowledge import abstract_text

CATEGORY_OBJECTIVES = {
    "crypto": "Identify the primitive and test the cheapest discriminating decode or attack.",
    "web": "Map supplied application evidence and propose one scoped, verifiable web hypothesis.",
    "pwn": "Determine mitigations, input boundary, and a plausible exploitation primitive statically.",
    "rev": "Recover control flow, constants, and the candidate validation transformation statically.",
    "forensics": "Identify containers and metadata, then test the most likely hidden-data layer.",
    "misc": "Classify the representation and reduce it to a more specific, testable problem.",
}


def plan_agent_wave(context: dict[str, Any]) -> dict[str, Any]:
    """Return two to four distinct, minimal-context assignments for one solve wave."""
    challenge = context.get("challenge", {})
    categories = [str(item) for item in challenge.get("categories", [])]
    artifacts = [str(item) for item in challenge.get("artifacts", [])]
    assignments: list[dict[str, Any]] = []
    if artifacts:
        assignments.append({
            "role": "artifact-triage",
            "objective": "Classify declared artifacts and return the highest-value next parser or transform.",
            "inputs": {"artifacts": artifacts[:32]},
            "deliverable": "Observed formats, concrete evidence, and one ranked next action.",
            "max_turns": 4,
        })
    for category in categories[:2] or ["misc"]:
        assignments.append({
            "role": f"{category}-specialist",
            "objective": CATEGORY_OBJECTIVES.get(category, CATEGORY_OBJECTIVES["misc"]),
            "inputs": {"run_id": context.get("run_id"), "category": category},
            "deliverable": "Hypothesis, supporting observation, falsifier, and one next tool action.",
            "max_turns": 6,
        })
    assignments.append({
        "role": "independent-critic",
        "objective": "Challenge the leading hypothesis and check that a candidate is not mistaken for proof.",
        "inputs": {"run_id": context.get("run_id")},
        "deliverable": "One material risk or contradiction, plus verification required to resolve it.",
        "max_turns": 4,
    })
    unique: list[dict[str, Any]] = []
    roles: set[str] = set()
    for assignment in assignments:
        if assignment["role"] not in roles:
            roles.add(assignment["role"])
            unique.append(assignment)
    unique = unique[:4]
    for assignment in unique:
        assignment.update({
            "model_policy": "smallest-capable-lower-tier",
            "context_policy": "no-history; provide only referenced evidence",
            "may_submit": False,
            "may_expand_scope": False,
        })
    return {
        "run_id": context.get("run_id"),
        "architecture": "planner-fresh-executors-compact-summaries",
        "assignments": unique,
        "synthesis_gate": {
            "required_fields": ["hypothesis", "evidence", "next_action"],
            "reject": ["duplicate_action", "unsupported_candidate", "scope_expansion"],
            "official_submission_owner": "Daybreak",
        },
        "next_wave_rule": "Start another wave only for unresolved, materially different hypotheses.",
    }


class AgentLedger:
    """Persist bounded subagent waves and evidence-backed compact reports."""

    def __init__(self, database):
        self.database = database
        self.session = CodexSession(database)
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_agent_waves (
                wave_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, plan TEXT NOT NULL,
                created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_agent_reports (
                report_id TEXT PRIMARY KEY, wave_id TEXT NOT NULL, run_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL, payload TEXT NOT NULL, action_key TEXT NOT NULL,
                created REAL NOT NULL, UNIQUE(wave_id, assignment_id))""")

    def create_wave(self, run_id: str) -> dict[str, Any]:
        context = self.session.context(run_id)
        plan = plan_agent_wave(context)
        wave_id = uuid4().hex
        plan["wave_id"] = wave_id
        for index, assignment in enumerate(plan["assignments"], 1):
            assignment["assignment_id"] = f"{wave_id}:{index}"
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO ctf_agent_waves(wave_id,run_id,plan,created) VALUES (?,?,?,?)",
                       (wave_id, run_id, json.dumps(plan, sort_keys=True), time.time()))
        return plan

    def record_report(self, run_id: str, wave_id: str, assignment_id: str,
                      report: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(run_id, wave_id)
        assignments = {item["assignment_id"] for item in plan["assignments"]}
        if assignment_id not in assignments:
            raise ValueError("assignment does not belong to this wave")
        required = ("hypothesis", "evidence", "falsifier", "next_action")
        values: dict[str, str] = {}
        for field in required:
            value = report.get(field)
            if not isinstance(value, str) or not 5 <= len(value) <= 2000:
                raise ValueError(f"{field} must be a concise substantive string")
            values[field] = abstract_text(value)
        status = report.get("status", "inconclusive")
        if status not in {"supported", "rejected", "inconclusive"}:
            raise ValueError("invalid report status")
        sequences = report.get("event_sequences")
        if (not isinstance(sequences, list) or not sequences or len(sequences) > 20
                or any(not isinstance(item, int) or item < 0 for item in sequences)):
            raise ValueError("event_sequences must reference observed run evidence")
        existing_sequences = {event.sequence for event in self.session.store.read(run_id)}
        if not set(sequences).issubset(existing_sequences):
            raise ValueError("report references unknown run evidence")
        action_key = hashlib.sha256(" ".join(values["next_action"].lower().split()).encode()).hexdigest()
        with sqlite3.connect(self.database) as db:
            duplicate = db.execute(
                "SELECT 1 FROM ctf_agent_reports WHERE run_id=? AND action_key=? LIMIT 1",
                (run_id, action_key),
            ).fetchone()
            if duplicate:
                raise ValueError("duplicate next action")
            report_id = uuid4().hex
            payload = {**values, "status": status, "event_sequences": sequences}
            db.execute("""INSERT INTO ctf_agent_reports
                (report_id,wave_id,run_id,assignment_id,payload,action_key,created)
                VALUES (?,?,?,?,?,?,?)""",
                (report_id, wave_id, run_id, assignment_id,
                 json.dumps(payload, sort_keys=True), action_key, time.time()))
        return {"report_id": report_id, "wave_id": wave_id, "assignment_id": assignment_id,
                "stored": True, "candidate_stored": False}

    def synthesize(self, run_id: str, wave_id: str) -> dict[str, Any]:
        plan = self._plan(run_id, wave_id)
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "SELECT report_id,assignment_id,payload FROM ctf_agent_reports "
                "WHERE run_id=? AND wave_id=? ORDER BY created", (run_id, wave_id),
            ).fetchall()
        reports = [{"report_id": identity, "assignment_id": assignment,
                    **json.loads(payload)} for identity, assignment, payload in rows]
        expected = {item["assignment_id"] for item in plan["assignments"]}
        received = {item["assignment_id"] for item in reports}
        missing = sorted(expected - received)
        status = self.session.context(run_id)["status"]
        return {
            "run_id": run_id,
            "wave_id": wave_id,
            "complete": not missing,
            "missing_assignments": missing,
            "reports": reports,
            "supported_hypotheses": [item["hypothesis"] for item in reports
                                     if item["status"] == "supported"],
            "contradictions": [item["falsifier"] for item in reports
                               if item["status"] == "rejected"],
            "next_actions": [item["next_action"] for item in reports],
            "submission": {"owner": "orchestrator", "allowed": status == "solved",
                           "reason": "official_verifier_required" if status != "solved"
                           else "already_verified"},
            "start_another_wave": not missing and not any(
                item["status"] == "supported" for item in reports),
        }

    def _plan(self, run_id: str, wave_id: str) -> dict[str, Any]:
        self.session.context(run_id)
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT plan FROM ctf_agent_waves WHERE run_id=? AND wave_id=?",
                             (run_id, wave_id)).fetchone()
        if not row:
            raise ValueError("unknown agent wave")
        return json.loads(row[0])
