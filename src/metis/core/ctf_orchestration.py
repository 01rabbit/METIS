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

from pydantic import ValidationError

from metis.core.agent_contracts import (
    PROFILES,
    SCHEMA_VERSION,
    TERMINAL_JOB_STATES,
    CompactReport,
    ExecutionMode,
    ProposedAction,
    decide_wave,
)
from metis.core.codex_session import CodexSession
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, DERIVE_TOOLS
from metis.core.ctf_knowledge import abstract_text
from metis.core.ctf_tools import DATA_TOOLS
from metis.core.intent_identity import intent_identity


def assigned_artifact_scope(assignment: dict[str, Any], declared_artifacts: set[str]) -> set[str] | None:
    """Validate an optional assignment-level artifact capability.

    A missing ``inputs.artifacts`` preserves run-wide artifact access. An
    explicit empty list grants no artifact access.
    """
    inputs = assignment.get("inputs", {})
    if not isinstance(inputs, dict):
        raise TypeError("invalid assignment inputs")
    if "artifacts" not in inputs:
        return None
    refs = inputs["artifacts"]
    if (not isinstance(refs, list) or len(refs) > 32
            or any(not isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs)) or not set(refs) <= declared_artifacts):
        raise ValueError("invalid assignment artifact scope")
    return set(refs)

CATEGORY_OBJECTIVES = {
    "crypto": "Identify the primitive and test the cheapest discriminating decode or attack.",
    "web": "Map supplied application evidence and propose one scoped, verifiable web hypothesis.",
    "pwn": "Determine mitigations, input boundary, and a plausible exploitation primitive statically.",
    "rev": "Recover control flow, constants, and the candidate validation transformation statically.",
    "forensics": "Identify containers and metadata, then test the most likely hidden-data layer.",
    "misc": "Classify the representation and reduce it to a more specific, testable problem.",
}
SECONDS_PER_TURN = 150


def plan_agent_wave(context: dict[str, Any], *, force_mode: ExecutionMode | None = None) -> dict[str, Any]:
    """Deterministic wave plan: sequential for simple problems, 2-4 distinct roles otherwise.

    Pure policy (no model calls, no database). ``assignments`` lists only the roles that
    must report; in sequential mode it is empty and ``daybreak_covers`` names the roles
    Daybreak handles itself, so nothing is left "missing".
    """
    decision = decide_wave(context, force_mode=force_mode)
    challenge = context.get("challenge", {})
    artifacts = [str(item) for item in challenge.get("artifacts", [])][:32]
    remaining = int(context.get("seconds_remaining") or 3600)
    assignments: list[dict[str, Any]] = []
    for role in decision.required_roles:
        profile = PROFILES[role]
        deadline = max(60, min(profile.max_turns * SECONDS_PER_TURN, remaining or 60))
        inputs: dict[str, Any] = {"run_id": context.get("run_id")}
        if role == "artifact-triage":
            inputs = {"artifacts": artifacts}
        elif profile.category:
            inputs["category"] = profile.category
        assignments.append({
            "role": role,
            "objective": CATEGORY_OBJECTIVES.get(profile.category or "", profile.objective),
            "inputs": inputs,
            "deliverable": profile.deliverable,
            "max_turns": profile.max_turns,
            "deadline_seconds": deadline,
            "tier": profile.tier,
            "recommended_tools": profile.recommended_tools,
            "model_policy": "smallest-capable-lower-tier" if profile.tier == "lower" else "active-catalog-standard",
            "context_policy": "no-history; provide only referenced evidence",
            "may_submit": False,
            "may_expand_scope": False,
            "may_handle_credentials": False,
            "may_delegate": False,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": context.get("run_id"),
        "architecture": "planner-fresh-executors-compact-summaries",
        "execution_mode": decision.execution_mode,
        "decision": decision.model_dump(),
        "daybreak_covers": decision.daybreak_covers,
        "assignments": assignments,
        "synthesis_gate": {
            "required_fields": ["hypothesis", "evidence", "next_action"],
            "reject": ["duplicate_action", "unsupported_candidate", "scope_expansion", "stale_attempt"],
            "official_submission_owner": "Daybreak",
        },
        "next_wave_rule": "Start another wave only for unresolved, materially different hypotheses "
                          "with budget left, after this wave is ready for synthesis.",
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(ctf_agent_reports)")}
            for name in ("attempt_id", "action_identity", "evidence_action_identity"):
                if name not in columns:
                    db.execute(f"ALTER TABLE ctf_agent_reports ADD COLUMN {name} TEXT")

    def create_wave(self, run_id: str, *, mode: ExecutionMode | None = None,
                    reason: str | None = None) -> dict[str, Any]:
        """Plan a wave. A further wave needs the previous one ready for synthesis, budget
        left, and a stated, materially different hypothesis (``reason``)."""
        context = self.session.context(run_id)
        with sqlite3.connect(self.database) as db:
            previous = db.execute("SELECT wave_id FROM ctf_agent_waves WHERE run_id=? ORDER BY created DESC LIMIT 1",
                                  (run_id,)).fetchone()
        if previous:
            decision = self.synthesize(run_id, previous[0])["decision"]
            if not decision["ready_for_synthesis"]:
                raise ValueError("previous wave still has unresolved required assignments; collect, cancel "
                                 "or time them out first")
            if not context["actions_remaining"] or not context["seconds_remaining"]:
                raise ValueError("no budget left for another wave")
            turn_budget = self._specialist_turn_budget(run_id)
            if turn_budget is not None and turn_budget["remaining"] <= 0:
                raise ValueError("no specialist model turns left for another wave")
            if not reason or len(reason.strip()) < 10:
                raise ValueError("a new wave needs --reason naming the unresolved, different hypothesis")
            abstract_text(reason)
            normalized_reason = " ".join(reason.casefold().split())
            with sqlite3.connect(self.database) as db:
                prior_plans = [json.loads(row[0]) for row in db.execute(
                    "SELECT plan FROM ctf_agent_waves WHERE run_id=?", (run_id,)).fetchall()]
            if any(" ".join(str(plan.get("reason", "")).casefold().split()) == normalized_reason
                   for plan in prior_plans):
                raise ValueError("a new wave needs a distinct reason; this rationale was already used")
        plan = plan_agent_wave(context, force_mode=mode)
        wave_id = uuid4().hex
        plan["wave_id"] = wave_id
        if reason:
            plan["reason"] = reason.strip()[:500]
        for index, assignment in enumerate(plan["assignments"], 1):
            assignment["assignment_id"] = f"{wave_id}:{index}"
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO ctf_agent_waves(wave_id,run_id,plan,created) VALUES (?,?,?,?)",
                       (wave_id, run_id, json.dumps(plan, sort_keys=True), time.time()))
        return plan

    def _specialist_turn_budget(self, run_id: str) -> dict[str, int] | None:
        with sqlite3.connect(self.database) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_run_turn_budgets'"
            ).fetchone()
            row = (db.execute(
                "SELECT turn_limit,turns_reserved FROM agent_run_turn_budgets WHERE run_id=?", (run_id,)
            ).fetchone() if exists else None)
        if row is None:
            return None
        return {"limit": row[0], "reserved": row[1], "remaining": row[0] - row[1]}

    def record_report(self, run_id: str, wave_id: str, assignment_id: str,
                      report: dict[str, Any], *, attempt_id: str | None = None) -> dict[str, Any]:
        plan = self._plan(run_id, wave_id)
        assignments = {item["assignment_id"] for item in plan["assignments"]}
        if assignment_id not in assignments:
            raise ValueError("assignment does not belong to this wave")
        self._check_attempt(assignment_id, attempt_id)
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
                or any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in sequences)):
            raise ValueError("event_sequences must reference observed run evidence")
        try:
            parsed = CompactReport.model_validate({key: value for key, value in report.items()})
        except ValidationError as exc:
            raise ValueError("report has unknown or invalid fields: " +
                             "; ".join(sorted({".".join(map(str, e["loc"])) for e in exc.errors()}))) from None
        existing_sequences = {event.sequence for event in self.session.store.read(run_id)}
        if not set(sequences).issubset(existing_sequences):
            raise ValueError("report references unknown run evidence")
        declared = set(self.session.context(run_id)["challenge"].get("artifacts", []))
        if set(parsed.artifact_refs) - declared:
            raise ValueError("report references artifacts that are not registered in this run")
        assignment = next(item for item in plan["assignments"] if item["assignment_id"] == assignment_id)
        allowed_artifacts = assigned_artifact_scope(assignment, declared)
        if allowed_artifacts is not None and set(parsed.artifact_refs) - allowed_artifacts:
            raise ValueError("report references artifacts outside this assignment's scope")
        proposed_identity = None
        if parsed.next_action_intent is not None:
            try:
                proposed = ProposedAction.model_validate(parsed.next_action_intent)
            except ValidationError:
                raise ValueError("next_action_intent must be a bounded METIS tool request") from None
            supported = ((proposed.kind == "data" and proposed.tool in DATA_TOOLS)
                         or (proposed.kind == "artifact" and proposed.tool in ARTIFACT_TOOLS
                             and set(proposed.options) <= ALLOWED_OPTIONS[proposed.tool])
                         or (proposed.kind == "derive" and proposed.tool in DERIVE_TOOLS
                             and set(proposed.options) <= ALLOWED_OPTIONS[proposed.tool])
                         or (proposed.kind == "view" and proposed.tool == "view"))
            if not supported:
                raise ValueError("next_action_intent names an unsupported tool or option")
            if proposed.kind in {"artifact", "derive", "view"}:
                if proposed.artifact not in declared:
                    raise ValueError("next_action_intent references an undeclared artifact")
                if allowed_artifacts is not None and proposed.artifact not in allowed_artifacts:
                    raise ValueError("next_action_intent artifact is outside this assignment's scope")
            proposed_identity, _family = intent_identity(proposed.kind, proposed.tool, proposed.artifact,
                                                         proposed.options, proposed.data,
                                                         self.session.artifact_root(run_id))
            if parsed.action_identity is not None and parsed.action_identity != proposed_identity:
                raise ValueError("action_identity must match next_action_intent")
        elif parsed.action_identity is not None:
            raise ValueError("action_identity requires a controller-checkable next_action_intent")
        action_key = hashlib.sha256(" ".join(values["next_action"].lower().split()).encode()).hexdigest()
        newest = max(sequences)
        with sqlite3.connect(self.database) as db:
            # A proposal is not proof that an operation actually ran. Only use its
            # structured identity for stuckness when the report cites an observation
            # produced by that exact controller-recorded action.
            evidence_action_identity = None
            if proposed_identity and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_actions'").fetchone():
                placeholders = ",".join("?" for _ in sequences)
                matched = db.execute(
                    f"SELECT 1 FROM agent_actions WHERE run_id=? AND identity=? "
                    f"AND sequence IN ({placeholders}) LIMIT 1",
                    (run_id, proposed_identity, *sequences),
                ).fetchone()
                if matched:
                    evidence_action_identity = proposed_identity
            if proposed_identity:
                rows = db.execute("SELECT payload FROM ctf_agent_reports WHERE run_id=? AND action_identity=?",
                                  (run_id, proposed_identity)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM ctf_agent_reports WHERE run_id=? AND action_identity IS NULL "
                                  "AND action_key=?", (run_id, action_key)).fetchall()
            # Same action again is allowed only when it rests on newer evidence (a real re-test).
            if any(newest <= max(json.loads(row[0])["event_sequences"]) for row in rows):
                raise ValueError("duplicate next action")
            report_id = uuid4().hex
            payload = {**values, "status": status, "event_sequences": sequences,
                       "artifact_refs": parsed.artifact_refs, "schema_version": SCHEMA_VERSION}
            db.execute("""INSERT INTO ctf_agent_reports
                (report_id,wave_id,run_id,assignment_id,payload,action_key,created,attempt_id,action_identity,
                 evidence_action_identity) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (report_id, wave_id, run_id, assignment_id, json.dumps(payload, sort_keys=True), action_key,
                 time.time(), attempt_id, proposed_identity, evidence_action_identity))
        return {"report_id": report_id, "wave_id": wave_id, "assignment_id": assignment_id,
                "stored": True, "candidate_stored": False}

    def _check_attempt(self, assignment_id: str, attempt_id: str | None) -> None:
        """Scheduled assignments only accept the report of their current running attempt."""
        with sqlite3.connect(self.database) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_jobs'").fetchone():
                return
            row = db.execute("SELECT attempt_id, state FROM agent_jobs WHERE assignment_id=?",
                             (assignment_id,)).fetchone()
            if row is None:
                return  # Unscheduled (legacy/manual) assignment.
            current, state = row
            if attempt_id != current or state != "running":
                db.execute("INSERT INTO agent_job_log(assignment_id,attempt_id,event,detail,time) VALUES (?,?,?,?,?)",
                           (assignment_id, attempt_id or "-", "report_rejected",
                            f"current={current} state={state}", time.time()))
                raise ValueError("stale or unknown attempt; report rejected")

    def synthesize(self, run_id: str, wave_id: str) -> dict[str, Any]:
        plan = self._plan(run_id, wave_id)
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "SELECT report_id,assignment_id,payload FROM ctf_agent_reports "
                "WHERE run_id=? AND wave_id=? ORDER BY created", (run_id, wave_id),
            ).fetchall()
            jobs: dict[str, str] = {}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_jobs'").fetchone():
                jobs = dict(db.execute("SELECT assignment_id, state FROM agent_jobs WHERE wave_id=?",
                                       (wave_id,)).fetchall())
            all_rows = db.execute(
                "SELECT wave_id,payload,action_key,evidence_action_identity FROM ctf_agent_reports "
                "WHERE run_id=? ORDER BY created",
                (run_id,),
            ).fetchall()
            wave_order = [row[0] for row in db.execute(
                "SELECT wave_id FROM ctf_agent_waves WHERE run_id=? ORDER BY created", (run_id,)
            ).fetchall()]
        reports = [{"report_id": identity, "assignment_id": assignment,
                    **json.loads(payload)} for identity, assignment, payload in rows]
        expected = {item["assignment_id"] for item in plan["assignments"]}
        received = {item["assignment_id"] for item in reports}
        missing = sorted(expected - received)
        context = self.session.context(run_id)
        status = context["status"]
        ended = {assignment: state for assignment, state in jobs.items()
                 if assignment in missing and state in TERMINAL_JOB_STATES - {"completed"}}
        unresolved = [assignment for assignment in missing if assignment not in ended]
        supported = [item for item in reports if item["status"] == "supported"]
        open_hypotheses = [item["hypothesis"] for item in reports if item["status"] == "inconclusive"]
        grouped: dict[str, dict[str, Any]] = {}
        for item in reports:
            key = " ".join(item["hypothesis"].casefold().split())
            group = grouped.setdefault(key, {"hypothesis": item["hypothesis"], "supported": 0,
                                             "rejected": 0, "inconclusive": 0,
                                             "event_sequences": set()})
            group[item["status"]] += 1
            group["event_sequences"].update(item["event_sequences"])
        hypothesis_scores = [
            {"hypothesis": group["hypothesis"], "supported": group["supported"],
             "rejected": group["rejected"], "inconclusive": group["inconclusive"],
             "score": group["supported"] - group["rejected"],
             "event_sequences": sorted(group["event_sequences"]),
             "contradicted": bool(group["supported"] and group["rejected"])}
            for key, group in sorted(grouped.items())
        ]
        strategy_history: dict[tuple[str, str], dict[str, Any]] = {}
        for prior_wave_id, payload, action_key, action_identity in all_rows:
            if action_key is None:
                continue
            report = json.loads(payload)
            hypothesis_key = " ".join(report["hypothesis"].casefold().split())
            # The structured proposal identity is controller-derived from a bounded tool
            # request; free-text next_action remains the legacy fallback.
            history = strategy_history.setdefault((action_identity or action_key, hypothesis_key), {
                "action": report["next_action"], "hypothesis": report["hypothesis"],
                "wave_statuses": {},
            })
            history["wave_statuses"].setdefault(prior_wave_id, set()).add(report["status"])
        current_index = wave_order.index(wave_id)
        previous_wave_id = wave_order[current_index - 1] if current_index > 0 else None
        repeated_actions = [
            {"action": history["action"], "hypothesis": history["hypothesis"],
             "wave_count": len(history["wave_statuses"]),
             "stalled": (wave_id in history["wave_statuses"] and previous_wave_id is not None
                         and previous_wave_id in history["wave_statuses"]
                         and len(history["wave_statuses"][wave_id]) == 1
                         and history["wave_statuses"][wave_id] == history["wave_statuses"][previous_wave_id]),
             "statuses": sorted(set().union(*history["wave_statuses"].values()))}
            for _key, history in sorted(strategy_history.items()) if len(history["wave_statuses"]) > 1
        ]
        stuck = any(item["stalled"] for item in repeated_actions)
        stuckness = {"detected": stuck, "repeated_actions": repeated_actions,
                     "rule": "same normalized action and hypothesis with unchanged status across waves",
                     "recommendation": "select a distinct evidence-backed strategy" if stuck else None}
        contradicted_hypotheses = [item for item in hypothesis_scores if item["contradicted"]]
        contradiction_keys = {" ".join(item["hypothesis"].casefold().split())
                              for item in contradicted_hypotheses}
        contradicted = bool(contradicted_hypotheses)
        budget = bool(context["actions_remaining"] and context["seconds_remaining"])
        specialist_turn_budget = self._specialist_turn_budget(run_id)
        new_wave_reasons = []
        if unresolved:
            new_wave_reasons.append("required assignments unresolved")
        if not budget:
            new_wave_reasons.append("budget exhausted")
        if specialist_turn_budget is not None and specialist_turn_budget["remaining"] <= 0:
            new_wave_reasons.append("specialist model-turn budget exhausted")
        if not open_hypotheses and not contradicted:
            new_wave_reasons.append("no open or contradicted hypothesis")
        return {
            "run_id": run_id,
            "wave_id": wave_id,
            "complete": not missing,
            "specialist_turn_budget": specialist_turn_budget,
            "missing_assignments": missing,
            "reports": reports,
            "supported_hypotheses": [item["hypothesis"] for item in supported],
            "hypothesis_scores": hypothesis_scores,
            "contradicted_hypotheses": contradicted_hypotheses,
            "stuckness": stuckness,
            "contradictions": [item["falsifier"] for item in reports
                               if item["status"] == "rejected"
                               and " ".join(item["hypothesis"].casefold().split()) in contradiction_keys],
            "next_actions": [item["next_action"] for item in reports],
            "submission": {"owner": "orchestrator", "allowed": status == "solved",
                           "reason": "official_verifier_required" if status != "solved"
                           else "already_verified"},
            "start_another_wave": not missing and not supported,
            # Version 2 decision (legacy fields above keep their meaning).
            "decision": {
                "schema_version": SCHEMA_VERSION,
                "execution_mode": plan.get("execution_mode", "delegated"),
                "required": sorted(expected),
                "unresolved": unresolved,
                "ended_without_report": ended,
                "ready_for_synthesis": not unresolved,
                "complete": not missing,
                "open_hypotheses": open_hypotheses,
                "new_wave": {"allowed": not new_wave_reasons, "blocked_by": new_wave_reasons,
                             "requires": "--reason naming a materially different hypothesis"},
                "submission": {"route": "Daybreak re-derives the candidate privately and sends it with "
                                        "`metis web submit --candidate-file` (or browser + attest)",
                               "synthesis_is_not_permission": True},
            },
        }

    def _plan(self, run_id: str, wave_id: str) -> dict[str, Any]:
        self.session.context(run_id)
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT plan FROM ctf_agent_waves WHERE run_id=? AND wave_id=?",
                             (run_id, wave_id)).fetchone()
        if not row:
            raise ValueError("unknown agent wave")
        return json.loads(row[0])
