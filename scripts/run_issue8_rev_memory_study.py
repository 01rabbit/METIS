"""Run the preregistered Issue #8 exploratory Rev memory comparison.

Private candidates and controller state remain outside Git. A stopped invocation
never resumes a model attempt automatically; an operator must inspect it first.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from metis.core.agent_autopilot import autopilot
from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI
from metis.core.ctf_knowledge import KnowledgeBase
from metis.core.ctf_orchestration import AgentLedger
from metis.core.store import RunStore
from metis.evaluation.heldout_protocol import (
    Bindings,
    Protocol,
    bind_run,
    digest,
    finalize,
    reconcile_arm_dispatch,
    reconcile_memory_snapshots,
    schedule,
)
from metis.evaluation.heldout_study_export import RunAssignment

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/studies/issue8-rev-memory-protocol.json"
PROMPT = ROOT / "docs/studies/issue8-rev-memory-prompt.txt"
EXPECTED_PROTOCOL = "2204980da039f6716451a59817069ffeb743977e293e40811a8cd455426bc5bb"
EXPECTED_IMAGE = "sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b"
EXPECTED_BRIEFS = {
    "misdirection": "30f9f9116aa59fb56941ee30f5ea2ef64b1f81539c3c72d7903e01d632b96dad",
    "read-a-binary": "bb45d30b87922b15080f5c75cc8a7b2cf951319356af0da3fe5cbc169cbe229e",
}


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("study input is unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def preflight(database: Path, inputs: Path, oracles: Path) -> tuple[Protocol, dict[str, int]]:
    protocol = Protocol.model_validate_json(PROTOCOL.read_bytes())
    if digest(protocol) != EXPECTED_PROTOCOL or protocol.measurement != "real_model":
        raise ValueError("preregistered protocol changed")
    if _sha(PROMPT) != protocol.arm_config["full"].prompt_sha256:
        raise ValueError("common prompt changed")
    if any(config.prompt_sha256 != _sha(PROMPT) for config in protocol.arm_config.values()):
        raise ValueError("arm prompt mismatch")
    sandbox = json.loads((database.parent / "sandbox.json").read_text())
    if sandbox.get("image") != EXPECTED_IMAGE or sandbox.get("platform") != "linux/arm64":
        raise ValueError("sandbox image changed")
    if CodexCLI().check() != "0.169.0":
        raise ValueError("Codex CLI version changed")
    cards: dict[str, int] = {}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for card_digest in protocol.memory_card_digests:
            rows = db.execute("SELECT id,source_split FROM munin_cards WHERE digest=?", (card_digest,)).fetchall()
            if len(rows) != 1 or rows[0][1] not in {"practice", "competition"}:
                raise ValueError("preregistered practice card unavailable")
            cards[card_digest] = rows[0][0]
    for task in protocol.tasks:
        artifact = inputs / task.task_id
        brief = ROOT / f"docs/studies/issue8-{task.task_id}-brief.txt"
        candidate = oracles / f"{task.task_id}.candidate"
        if _sha(artifact) != task.distribution_sha256 or _sha(brief) != EXPECTED_BRIEFS[task.task_id]:
            raise ValueError("official distribution or task brief changed")
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_mode & 0o077:
            raise ValueError("protected oracle file is unavailable or accessible to others")
        if not candidate.read_bytes() or len(candidate.read_bytes()) > 256:
            raise ValueError("protected oracle candidate size is invalid")
    return protocol, cards


def validate_completed_prefix(protocol: Protocol, database: Path, state: dict[str, Any]) -> None:
    """Fail closed on a changed progress file or controller ledger before new work."""
    rows = state.get("slots")
    if state.get("protocol_sha256") != EXPECTED_PROTOCOL or not isinstance(rows, list):
        raise ValueError("invalid saved study progress")
    planned = schedule(protocol)
    if len(rows) > len(planned):
        raise ValueError("saved study has too many slots")
    assignments: list[RunAssignment] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or {key: row.get(key) for key in planned[index]} != planned[index]:
            raise ValueError("saved study slot order differs from protocol")
        if row.get("phase") != "finished":
            raise RuntimeError("interrupted held-out run needs manual reconciliation")
        if not isinstance(row.get("stop"), str) or type(row.get("candidate_proposed")) is not bool:
            raise ValueError("saved outcome is incomplete")
        if row.get("local_control_match") is not None and type(row.get("local_control_match")) is not bool:
            raise ValueError("saved local outcome is invalid")
        assignment = RunAssignment.model_validate({key: row.get(key) for key in
                                                   ("task_id", "repetition", "arm", "run_id")})
        assignments.append(assignment)
    if len({item.run_id for item in assignments}) != len(assignments):
        raise ValueError("saved run identifier reused")
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='heldout_arm_bindings'").fetchone()
        bound = ({run_id for run_id, payload in db.execute("SELECT run_id,payload FROM heldout_arm_bindings")
                  if json.loads(payload).get("protocol_sha256") == EXPECTED_PROTOCOL} if table else set())
        if bound != {item.run_id for item in assignments}:
            raise ValueError("saved runs differ from controller bindings")
        for row, assignment in zip(rows, assignments, strict=True):
            run_id = assignment.run_id
            session = db.execute("SELECT evaluation_split FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()
            if session != ("heldout",):
                raise ValueError("saved run is not held out")
            events = RunStore(database, read_only=True).read(run_id)
            if not events or events[-1].status.value in {"executing", "observing", "replanning", "verifying"}:
                raise ValueError("saved run evidence is incomplete")
            jobs = db.execute("SELECT state FROM agent_jobs WHERE run_id=?", (run_id,)).fetchall()
            if not jobs or any(job[0] not in {"completed", "failed", "cancelled", "timed_out"} for job in jobs):
                raise ValueError("saved run has unresolved specialist work")
            budget = db.execute("SELECT turn_limit,turns_reserved FROM agent_run_turn_budgets WHERE run_id=?",
                                (run_id,)).fetchone()
            actual_calls = db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                                      (run_id,)).fetchone()[0]
            if (budget is None or budget[0] != protocol.budgets[assignment.arm].model_calls
                    or budget[1] != actual_calls or row.get("model_calls") != actual_calls):
                raise ValueError("saved model-call count differs from controller")
            candidate_count = db.execute("SELECT COUNT(*) FROM agent_candidates WHERE run_id=?", (run_id,)).fetchone()[0]
            if bool(candidate_count) != row["candidate_proposed"]:
                raise ValueError("saved candidate state differs from controller")
            local_success = events[-1].status.value == "solved" and (
                events[-1].detail.get("verification") == "local_sha256_commitment")
            if row["local_control_match"] != (local_success if candidate_count else None):
                raise ValueError("saved local outcome differs from run evidence")
            stops = db.execute("SELECT stop_reason FROM agent_autopilot_runs WHERE run_id=? ORDER BY started",
                               (run_id,)).fetchall()
            if len(stops) != 1 or stops[0][0] != row["stop"]:
                raise ValueError("saved stop reason differs from controller")
    partial = Bindings.model_construct(protocol_sha256=EXPECTED_PROTOCOL, runs=assignments)
    reconcile_memory_snapshots(protocol, partial, database)
    reconcile_arm_dispatch(protocol, partial, database)


def run(database: Path, inputs: Path, oracles: Path, progress: Path) -> dict[str, Any]:
    protocol, cards = preflight(database, inputs, oracles)
    if progress.exists():
        state = json.loads(progress.read_text())
        if state.get("protocol_sha256") != EXPECTED_PROTOCOL:
            raise ValueError("progress file belongs to another protocol")
    else:
        state = {"protocol_sha256": EXPECTED_PROTOCOL, "slots": []}
        _save(progress, state)
    validate_completed_prefix(protocol, database, state)
    if len(state["slots"]) != len(schedule(protocol)):
        raise RuntimeError("study is closed: token cap was not enforced; register a new controlled protocol")
    session = CodexSession(database)
    scheduler = AgentScheduler(database, BridgeHost(max_parallel=4))
    knowledge = KnowledgeBase(database)
    scheduler.configure(global_slots=4, per_run_slots=4, catalog=[],
                        current_model=protocol.model_pin, memory_retrieval=True)
    for index, slot in enumerate(schedule(protocol)):
        if index < len(state["slots"]):
            continue
        task = next(item for item in protocol.tasks if item.task_id == slot["task_id"])
        brief = ROOT / f"docs/studies/issue8-{task.task_id}-brief.txt"
        oracle_digest = _sha(oracles / f"{task.task_id}.candidate")
        created = session.intake(
            title=task.task_id, description=brief.read_text(),
            paths=[inputs / task.task_id, brief], categories=["rev"],
            commitment=oracle_digest, max_actions=protocol.budgets[slot["arm"]].actions,
            wall_seconds=int(protocol.budgets[slot["arm"]].seconds), evaluation_split="heldout",
        )
        run_id = created["run_id"]
        bind_run(protocol, database, run_id, **slot, expected_sha256=EXPECTED_PROTOCOL,
                 prompt_text=PROMPT.read_text())
        if protocol.arm_config[slot["arm"]].memory_enabled:
            knowledge.freeze_for_heldout(run_id, [cards[value] for value in protocol.memory_card_digests])
        record = {**slot, "run_id": run_id, "phase": "bound"}
        state["slots"].append(record)
        _save(progress, state)
        wave = AgentLedger(database).create_wave(run_id)
        if wave["execution_mode"] != "delegated" or len(wave["assignments"]) > 4:
            raise RuntimeError("study task did not produce the preregistered delegated plan")
        record["phase"] = "model_started"
        _save(progress, state)
        result = autopilot(scheduler, run_id, CodexCLI(), max_waves=1)
        candidates = [item for item in scheduler.candidates(run_id) if item["state"] == "pending"]
        local_match: bool | None = None
        if candidates:
            candidate_path = Path(candidates[0]["candidate_file"]).resolve(strict=True)
            if not candidate_path.is_relative_to(database.parent.resolve()):
                raise RuntimeError("candidate file escaped private controller state")
            local_match = session.submit(run_id, candidate_path.read_text(encoding="utf-8"))["verified"]
        record.update(phase="finished", stop=result["stop"], candidate_proposed=bool(candidates),
                      local_control_match=local_match,
                      model_calls=scheduler.model_turn_budget(run_id)["reserved"])
        _save(progress, state)
    bindings = Bindings.model_validate({"protocol_sha256": EXPECTED_PROTOCOL,
                                        "runs": [{key: row[key] for key in ("task_id", "repetition", "arm", "run_id")}
                                                 for row in state["slots"]]})
    _save(progress.parent / "bindings.json", bindings.model_dump(mode="json"))
    analysis = finalize(protocol, bindings, database, expected_sha256=EXPECTED_PROTOCOL)
    _save(progress.parent / "analysis.json", analysis)
    return {"protocol_sha256": EXPECTED_PROTOCOL, "runs": len(state["slots"]),
            "local_control_matches": sum(row["local_control_match"] is True for row in state["slots"]),
            "analysis": str(progress.parent / "analysis.json")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded preregistered Issue #8 Rev study")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--oracles", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="start the eight model trials after preflight")
    args = parser.parse_args()
    if not args.progress.parent.is_dir() or args.progress.is_symlink():
        raise ValueError("private progress directory is unavailable")
    descriptor = os.open(args.progress.parent / "study.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol, cards = preflight(args.database, args.inputs, args.oracles)
        if not args.run:
            print(json.dumps({"ready": True, "protocol_sha256": digest(protocol),
                              "slots": len(schedule(protocol)), "practice_cards": len(cards)}))
            return 0
        print(json.dumps(run(args.database, args.inputs, args.oracles, args.progress), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
