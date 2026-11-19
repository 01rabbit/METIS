"""Connect a pinned local Ollama runner to a newly registered held-out slot.

This is an execution entry point for a future study, not a study definition.
The historical Issue #8 exploratory protocol remains closed to new calls.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any

from metis.core.agent_autopilot import autopilot
from metis.core.agent_scheduler import AgentScheduler
from metis.core.ollama_token_budget import OllamaSpecialist, PinnedOllama
from metis.core.run_lock import run_lock
from metis.evaluation.heldout_arm import binding
from metis.evaluation.heldout_protocol import Protocol, digest

EXPLORATORY_PROTOCOL_SHA256 = "2204980da039f6716451a59817069ffeb743977e293e40811a8cd455426bc5bb"
OUTPUT_CAP_PER_TURN = 1024


def registered_runner(scheduler: AgentScheduler, run_id: str, protocol: Protocol,
                      *, expected_sha256: str, expected_runtime_sha256: str,
                      engine: PinnedOllama) -> OllamaSpecialist:
    """Fail before any specialist dispatch unless protocol, arm and budget are fixed.

    Every arm receives the same validated aggregate token budget and the same
    per-turn output allowance. The runner's SQLite ledger is keyed by run ID,
    so parallel specialists in that run share one cap.
    """
    protocol = Protocol.model_validate(protocol.model_dump())
    if (protocol.measurement != "real_model" or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or expected_sha256 == EXPLORATORY_PROTOCOL_SHA256 or digest(protocol) != expected_sha256):
        raise ValueError("a new real-model protocol must be preregistered")
    if not OllamaSpecialist.hard_token_budget_enforced:
        raise ValueError("pinned Ollama runtime cannot enforce a hard held-out token cap")
    if protocol.model_pin != engine.model:
        raise ValueError("study model differs from pinned Ollama model")
    bound = binding(scheduler.database, run_id)
    if bound is None or bound.get("protocol_sha256") != expected_sha256:
        raise ValueError("run does not belong to preregistered study")
    arm = bound.get("arm")
    if arm not in protocol.arms:
        raise ValueError("run arm is not in preregistered study")
    if (bound.get("model_pin") != protocol.model_pin or bound.get("runtime_pin") != protocol.runtime_pin
            or bound.get("arm_config") != protocol.arm_config[arm].model_dump(mode="json")
            or bound.get("budget") != protocol.budgets[arm].model_dump(mode="json")):
        raise ValueError("run treatment or budget differs from preregistration")
    if bound.get("task_id") not in {task.task_id for task in protocol.tasks}:
        raise ValueError("run task is not in preregistered study")
    if type(bound.get("repetition")) is not int or not 0 <= bound["repetition"] < protocol.repetitions:
        raise ValueError("run repetition is not in preregistered study")
    budget = protocol.budgets[arm]
    if budget.tokens <= OUTPUT_CAP_PER_TURN:
        raise ValueError("token budget cannot admit an input plus one output reservation")
    # Hashes, manifest layer and local tag are checked before autopilot can
    # reserve a model turn. PinnedOllama repeats this check on each call.
    engine.verify_model()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_runtime_sha256):
        raise ValueError("runtime profile digest must be externally fixed")
    profile = engine.runtime_profile(OUTPUT_CAP_PER_TURN)
    actual_runtime = hashlib.sha256(json.dumps(profile, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    if actual_runtime != expected_runtime_sha256:
        raise ValueError("pinned Ollama runtime differs from preregistered profile")
    with run_lock(scheduler.database, "study-" + expected_sha256), sqlite3.connect(scheduler.database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS heldout_ollama_study_runtime "
                       "(protocol_sha256 TEXT PRIMARY KEY, runtime_sha256 TEXT NOT NULL)")
            row = db.execute("SELECT runtime_sha256 FROM heldout_ollama_study_runtime "
                             "WHERE protocol_sha256=?", (expected_sha256,)).fetchone()
            if row is not None and row[0] != actual_runtime:
                raise ValueError("runtime profile changed between study arms")
            if row is None:
                db.execute("INSERT INTO heldout_ollama_study_runtime VALUES (?,?)",
                           (expected_sha256, actual_runtime))
    return OllamaSpecialist(scheduler.database, run_id, engine, OUTPUT_CAP_PER_TURN)


def run_registered_slot(scheduler: AgentScheduler, run_id: str, protocol: Protocol,
                        *, expected_sha256: str, expected_runtime_sha256: str,
                        engine: PinnedOllama) -> dict[str, Any]:
    """Run one already bound slot through the shared-budget Ollama specialist."""
    runner = registered_runner(scheduler, run_id, protocol,
                               expected_sha256=expected_sha256,
                               expected_runtime_sha256=expected_runtime_sha256, engine=engine)
    return autopilot(scheduler, run_id, runner, max_waves=1)
