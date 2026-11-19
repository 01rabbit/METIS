"""Run-scoped held-out treatment binding and dispatch evidence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from metis.core.run_lock import run_lock
from metis.core.store import RunStore


def binding(database: Path, run_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(database) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='heldout_arm_bindings'").fetchone():
            return None
        row = db.execute("SELECT payload FROM heldout_arm_bindings WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def bind(database: Path, run_id: str, payload: dict[str, Any]) -> None:
    """Bind a validated protocol slot before any run work or agent scheduling."""
    from metis.evaluation.heldout_analysis import Budget
    from metis.evaluation.heldout_protocol import ArmConfig, LlamaBackendPin

    config = ArmConfig.model_validate(payload["arm_config"])
    budget = Budget.model_validate(payload["budget"])
    llama_pin = (LlamaBackendPin.model_validate(payload["llama_backend"])
                 if payload.get("llama_backend") is not None else None)
    if llama_pin is not None and llama_pin.database_path != str(database.resolve()):
        raise ValueError("llama budget database does not match held-out state")
    prompt_text = payload.get("prompt_text")
    if payload.get("measurement") == "real_model":
        if (not isinstance(prompt_text, str) or not prompt_text.strip()
                or len(prompt_text.encode("utf-8")) > 4_000
                or hashlib.sha256(prompt_text.encode("utf-8")).hexdigest() != config.prompt_sha256):
            raise ValueError("held-out prompt does not match committed digest")
    elif prompt_text is not None:
        raise ValueError("synthetic fixture cannot bind a model prompt")
    if payload.get("arm") not in {"full", "without_memory", "without_planner", "single_agent"}:
        raise ValueError("invalid held-out arm")
    if payload.get("protocol_sha256") is None or len(payload["protocol_sha256"]) != 64:
        raise ValueError("invalid protocol digest")
    with run_lock(database, run_id):
        events = RunStore(database).read(run_id)
        if len(events) != 4 or [event.status.value for event in events] != [
            "new", "validated", "classified", "planning",
        ]:
            raise ValueError("held-out arm must be bound before work")
        with sqlite3.connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT evaluation_split,max_actions,wall_seconds FROM codex_sessions "
                             "WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0] != "heldout":
                raise ValueError("held-out arm requires held-out run")
            if row[1] > budget.actions or row[2] > budget.seconds:
                raise ValueError("held-out session exceeds protocol budget")
            db.execute("CREATE TABLE IF NOT EXISTS heldout_arm_bindings "
                       "(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            if db.execute("SELECT 1 FROM heldout_arm_bindings WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("held-out arm is already bound")
            stored = {"protocol_sha256": payload["protocol_sha256"], "study_id": payload["study_id"],
                      "measurement": payload["measurement"], "task_id": payload["task_id"],
                      "repetition": payload["repetition"], "arm": payload["arm"],
                      "arm_config": config.model_dump(mode="json"), "model_pin": payload["model_pin"],
                      "runtime_pin": payload["runtime_pin"], "budget": budget.model_dump(mode="json"),
                      "prompt_text": prompt_text,
                      "memory_card_digests": payload.get("memory_card_digests", [])}
            if llama_pin is not None:
                stored["llama_backend"] = llama_pin.model_dump(mode="json", exclude_none=True)
            db.execute("INSERT INTO heldout_arm_bindings VALUES (?,?)",
                       (run_id, json.dumps(stored, sort_keys=True)))
