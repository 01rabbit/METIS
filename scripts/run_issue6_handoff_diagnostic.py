#!/usr/bin/env python3
"""Run the preregistered symmetric Issue #6 synthetic replication."""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import random
import shutil
import sqlite3
import string
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI, run_assignment
from metis.core.ctf_orchestration import AgentLedger
from metis.core.verification import FixtureOracle

MODEL = "gpt-6.1-sol"
CLI_VERSION = "0.169.0"
STUDY_ID = "issue6-handoff-diagnostic-2026-11-18"
SEED = 20261119
ORDER_SEED = SEED ^ 0x6A09E667
BUDGET = {"turns": 8, "actions": 4, "slots": 2, "wall_seconds": 600}
ENCODINGS = ("base64", "base32", "hex", "base85", "base64url", "percent")
FAMILIES = list(combinations(ENCODINGS, 2))
TASK_REPETITIONS = 1
TASK_PREFIX = "task"
EVALUATION_SPLIT = "heldout"
COMPONENT_ALPHABET = (string.ascii_letters + string.digits + " .,;:-_!?()[]{}").encode()
OUTPUT = Path("docs/reports/data/issue6-handoff-diagnostic-2026-11-18.json")
ORACLE_FILE: Path


class PinnedCodexCLI(CodexCLI):
    def argv(self, workdir: Path, schema: Path, output: Path, model: str | None) -> list[str]:
        command = super().argv(workdir, schema, output, model)
        return [*command[:-1], "-c", 'model_reasoning_effort="low"', command[-1]]


def encode(kind: str, value: bytes) -> bytes:
    if kind == "base64":
        return base64.b64encode(value)
    if kind == "base32":
        return base64.b32encode(value)
    if kind == "hex":
        return value.hex().encode()
    if kind == "base85":
        return base64.b85encode(value)
    if kind == "base64url":
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    if kind == "percent":
        return urllib.parse.quote_from_bytes(value, safe="").encode()
    raise ValueError(kind)


def make_plan(ledger: AgentLedger, run_id: str, arm: str) -> dict[str, Any]:
    plan = ledger.create_wave(run_id, mode="delegated")
    by_role = {item["role"]: item for item in plan["assignments"]}
    artifacts = list(ledger.session.context(run_id)["challenge"]["artifacts"])
    if arm in {"single", "conditional"}:
        assignments = [dict(by_role["crypto-specialist"])]
        assignments[0]["inputs"] = {"artifacts": artifacts}
        # max_turns is the mediated-action cap, not the model-call cap. Reserve
        # two of four actions for a possible second wave.
        assignments[0]["max_turns"] = BUDGET["turns"] if arm == "single" else 2
        assignments[0]["objective"] = (
            "Decode both independent components and return only the two components, as JSON lowercase hex. "
            "Do not compute the final digest.")
        notes = {assignments[0]["assignment_id"]:
                 'Use bounded METIS intents to decode both artifacts. Privately return one JSON object '
                 'with keys "component0_hex" and "component1_hex", each the exact decoded bytes in '
                 'lowercase hex. Use candidate_report when the candidate and report are both ready; otherwise '
                 'use the separate candidate/report sequence. Never return plaintext or compute the final digest.'}
    elif arm in {"multi_separate", "multi_combined", "multi_fixed", "multi_borrow"}:
        assignments = [dict(by_role["crypto-specialist"]), dict(by_role["forensics-specialist"])]
        notes = {}
        for index, assignment in enumerate(assignments):
            assignment["inputs"] = {"artifacts": [artifacts[index]]}
            assignment["objective"] = f"Decode component {index}; privately return its exact bytes as lowercase hex."
            assignment["max_turns"] = BUDGET["turns"] // 2
            if arm == "multi_separate":
                handoff = ("Use the separate handoff: first send the exact decoded bytes privately using action "
                           "candidate, then submit your compact report in a later turn. Do not use candidate_report.")
            else:
                handoff = ("Use candidate_report to send the exact decoded bytes privately and the compact report "
                           "in the same turn when both are ready. The separate handoff remains available.")
            notes[assignment["assignment_id"]] = (
                "Inspect only your assigned artifact. Use a bounded METIS intent to decode it. " + handoff +
                " Do not return plaintext, the other component, or a final digest; keep all report text free "
                "of decoded data.")
    else:
        raise ValueError(arm)
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = [item["role"] for item in assignments]
    plan["daybreak_covers"] = []
    with sqlite3.connect(ledger.database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    return {"plan": plan, "notes": notes, "artifacts": artifacts}


def make_conditional_fallback(ledger: AgentLedger, run_id: str,
                              artifacts: list[str]) -> dict[str, Any]:
    """Start a different specialist only after the lead wave is terminal."""
    plan = ledger.create_wave(run_id, mode="delegated", reason=(
        "The crypto lead did not finish with a private candidate and report; "
        "test a forensics-led decode under the remaining run budget."))
    assignment = dict(next(item for item in plan["assignments"]
                           if item["role"] == "forensics-specialist"))
    assignment["inputs"] = {"artifacts": artifacts}
    assignment["max_turns"] = 2
    assignment["objective"] = "Independently decode both components; return their bytes as a private JSON hex pair."
    plan["assignments"] = [assignment]
    plan["decision"]["required_roles"] = [assignment["role"]]
    plan["daybreak_covers"] = []
    with sqlite3.connect(ledger.database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    note = ('Use bounded METIS intents to inspect both artifacts. Privately return one JSON object '
            'with component0_hex and component1_hex as lowercase hex. Use candidate_report when ready; '
            'keep decoded bytes out of reports. This is an independent fallback, not a continuation.')
    return {"plan": plan, "notes": {assignment["assignment_id"]: note}, "artifacts": artifacts}


def compose_candidate(arm: str, setup: dict[str, Any], candidates: dict[str, str]) -> str | None:
    assignments = setup["plan"]["assignments"]
    try:
        if arm in {"single", "conditional"}:
            if len(assignments) != 1:
                return None
            value = json.loads(candidates[assignments[0]["assignment_id"]])
            if not isinstance(value, dict) or set(value) != {"component0_hex", "component1_hex"}:
                return None
            component0 = bytes.fromhex(value["component0_hex"])
            component1 = bytes.fromhex(value["component1_hex"])
        else:
            if len(assignments) != 2:
                return None
            partials: list[bytes | None] = [None, None]
            for assignment in assignments:
                refs = assignment["inputs"]["artifacts"]
                index = setup["artifacts"].index(refs[0])
                partials[index] = bytes.fromhex(candidates[assignment["assignment_id"]])
            if any(part is None for part in partials):
                return None
            if partials[0] is None or partials[1] is None:
                return None
            component0 = partials[0]
            component1 = partials[1]
            assert component0 is not None and component1 is not None
        return hashlib.sha256(component0 + b"\0" + component1).hexdigest()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def run_arm(session: CodexSession, scheduler: AgentScheduler, runner: PinnedCodexCLI, base: Path,
            case_id: str, components: tuple[bytes, bytes], family: tuple[str, str], arm: str,
            *, oracle_file: Path | None = None,
            evaluation_split: str = EVALUATION_SPLIT) -> dict[str, Any]:
    paths = []
    for index, (kind, component) in enumerate(zip(family, components, strict=True)):
        path = base / f"{case_id}-{arm}-component-{index}.txt"
        path.write_bytes(encode(kind, component))
        paths.append(path)
    started = time.monotonic()
    description = (
        "Two independent artifacts contain printable text components encoded using one of Base64, Base32, "
        "hex, Base85, Base64URL, or percent encoding. Identify and decode them using bounded METIS intents. "
        "Return decoded components only in the private candidate channel as lowercase hex; the controller "
        "computes SHA-256(component 0 + NUL + component 1) and uses a protected local oracle.")
    run_id = session.intake(title=f"Synthetic paired benchmark {case_id}", description=description,
                            paths=paths, categories=["crypto", "forensics"], max_actions=BUDGET["actions"],
                            wall_seconds=BUDGET["wall_seconds"], evaluation_split=evaluation_split)["run_id"]
    run_root = session.artifact_root(run_id)
    if run_root is None:
        raise RuntimeError("run artifact root is unavailable")
    oracle = FixtureOracle(oracle_file or ORACLE_FILE, solver_roots=(run_root,))
    scheduler.configure(global_slots=BUDGET["slots"], per_run_slots=BUDGET["slots"],
                        specialist_turn_budget=BUDGET["turns"],
                        catalog=[{"id": MODEL, "tier": "standard"}], current_model=MODEL,
                        memory_retrieval=False)
    setup = make_plan(scheduler.ledger, run_id, arm)
    scheduler.enqueue(run_id, setup["plan"]["wave_id"], dynamic_borrowing=arm == "multi_borrow")
    started_jobs = scheduler.dispatch(run_id)["started"]
    results: dict[str, dict[str, Any]] = {}

    def drive(job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        assignment_id = job["assignment_id"]
        result = run_assignment(scheduler, run_id, assignment_id, job["attempt_id"], runner,
                                model=MODEL, turn_timeout=180,
                                note=setup["notes"][assignment_id],
                                allow_candidate_report=arm != "multi_separate")
        return assignment_id, result

    if len(started_jobs) == 1:
        key, result = drive(started_jobs[0])
        results[key] = result
    elif len(started_jobs) == 2:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for key, result in pool.map(drive, started_jobs):
                results[key] = result
    else:
        scheduler.cancel_run(run_id)
    synthesis = scheduler.ledger.synthesize(run_id, setup["plan"]["wave_id"])
    fallback_dispatched = False
    fallback_setup: dict[str, Any] | None = None
    if arm == "conditional":
        lead_id = setup["plan"]["assignments"][0]["assignment_id"]
        lead_ready = any(row["assignment_id"] == lead_id and row["state"] == "pending"
                         and row.get("candidate_file") for row in scheduler.candidates(run_id))
        lead_completed = results[lead_id]["job_state"] == "completed" and synthesis["complete"]
        if not (lead_ready and lead_completed):
            try:
                fallback_setup = make_conditional_fallback(scheduler.ledger, run_id, setup["artifacts"])
            except ValueError:
                fallback_setup = None  # Shared action, wall, or call budget forbids another wave.
            if fallback_setup is not None:
                scheduler.enqueue(run_id, fallback_setup["plan"]["wave_id"])
                fallback_jobs = scheduler.dispatch(run_id)["started"]
                if len(fallback_jobs) == 1:
                    fallback_dispatched = True
                    fallback_job = fallback_jobs[0]
                    assignment_id = fallback_job["assignment_id"]
                    results[assignment_id] = run_assignment(
                        scheduler, run_id, assignment_id, fallback_job["attempt_id"], runner,
                        model=MODEL, turn_timeout=180,
                        note=fallback_setup["notes"][assignment_id], allow_candidate_report=True)
                synthesis = scheduler.ledger.synthesize(run_id, fallback_setup["plan"]["wave_id"])
    listed = scheduler.candidates(run_id)
    candidate_ready = {row["assignment_id"] for row in listed
                       if row["state"] == "pending" and row.get("candidate_file")}
    candidate_values: dict[str, str] = {}
    for row in listed:
        candidate_file = row.get("candidate_file")
        if candidate_file and row["state"] == "pending":
            candidate_values[row["assignment_id"]] = Path(candidate_file).read_text(encoding="utf-8").strip()
    scheduler.candidates(run_id, purge="all")
    if arm == "conditional":
        candidate_sources = [(setup, setup["plan"]["assignments"][0]["assignment_id"])]
        if fallback_setup is not None:
            candidate_sources.append((fallback_setup, fallback_setup["plan"]["assignments"][0]["assignment_id"]))
        verified_sources = [assignment_id for source, assignment_id in candidate_sources
                            if (candidate := compose_candidate("conditional", source, candidate_values)) is not None
                            and oracle.verify(case_id, candidate)]
        verified = bool(verified_sources)
        verified_assignment_state = next(
            (results.get(assignment_id, {}).get("job_state") for assignment_id in verified_sources
             if results.get(assignment_id, {}).get("job_state") == "completed"),
            results.get(verified_sources[0], {}).get("job_state") if verified_sources else None)
        winning_assignment_completed = verified_assignment_state == "completed"
    else:
        candidate = compose_candidate(arm, setup, candidate_values)
        verified = candidate is not None and oracle.verify(case_id, candidate)
        winning_assignment_completed = bool(verified and all(
            result["job_state"] == "completed" for result in results.values()))
        verified_assignment_state = ("completed" if winning_assignment_completed else None)
    turns = [turn for result in results.values() for turn in result.get("codex_turns", [])]
    usage_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
    usage = {key: sum((turn.get("usage") or {}).get(key, 0)
                      for turn in turns if isinstance((turn.get("usage") or {}).get(key, 0), int))
             for key in usage_keys}
    with sqlite3.connect(scheduler.database) as db:
        actions = db.execute("SELECT COUNT(*) FROM agent_actions WHERE run_id=?", (run_id,)).fetchone()[0]
        budget_denials = db.execute(
            "SELECT COUNT(*) FROM agent_job_log l JOIN agent_jobs j USING(assignment_id) "
            "WHERE j.run_id=? AND l.event='model_turn_budget_exhausted'", (run_id,)).fetchone()[0]
        peer_reserve_denials = db.execute(
            "SELECT COUNT(*) FROM agent_job_log l JOIN agent_jobs j USING(assignment_id) "
            "WHERE j.run_id=? AND l.event='model_turn_peer_reserve'", (run_id,)).fetchone()[0]
    model_budget = scheduler.model_turn_budget(run_id)
    states = [item["job_state"] for item in results.values()]
    decision_counts: dict[str, int] = {}
    for result in results.values():
        for action, count in result.get("decision_counts", {}).items():
            decision_counts[action] = decision_counts.get(action, 0) + int(count)
    report_rejections = sum("report_rejected" in step for result in results.values()
                            for step in result.get("intents", []))
    rejection_categories = {key: 0 for key in (
        "privacy", "schema_or_options", "evidence_provenance", "duplicate_action",
        "lifecycle_budget", "output_limit", "other_validation")}
    rejection_stages = {key: 0 for key in ("normalization", "persistence", "normalization_or_persistence")}
    for result in results.values():
        for step in result.get("intents", []):
            category = step.get("report_rejected")
            if category in rejection_categories:
                rejection_categories[category] += 1
                stage = step.get("report_rejection_stage")
                if stage in rejection_stages:
                    rejection_stages[stage] += 1
    terminal_categories: dict[str, int] = {}
    for job in scheduler.jobs(run_id):
        state = job["state"]
        failure = str(job.get("failure") or "").lower()
        if "deadline" in failure:
            category = "deadline"
        elif "budget" in failure or "turn" in failure:
            category = "call_budget_or_turn_limit"
        elif state in {"completed", "cancelled", "timed_out", "failed"}:
            category = state
        else:
            category = "other"
        terminal_categories[category] = terminal_categories.get(category, 0) + 1
    return {"case": case_id, "task_id": case_id.rsplit("-rep-", 1)[0], "arm": arm,
            "run_id": run_id, "oracle_verified": bool(verified),
            "workflow_verified": bool(verified and winning_assignment_completed),
            "verified_assignment_state": verified_assignment_state,
            "fallback_dispatched": fallback_dispatched,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "calls_observed": len(turns), "calls_reserved": model_budget["reserved"] if model_budget else None,
            "usage": usage, "usage_complete": bool(turns) and all(turn.get("usage") is not None for turn in turns),
            "actions": actions, "synthesis_complete": synthesis["complete"], "job_states": states,
            "candidate_ready_jobs": len(candidate_ready), "decision_counts": decision_counts,
            "report_rejections": report_rejections, "report_rejection_categories": rejection_categories,
            "report_rejection_stages": rejection_stages,
            "terminal_reason_categories": terminal_categories, "model_turn_budget_denials": budget_denials,
            "peer_reserve_denials": peer_reserve_denials,
            "model": MODEL, "cli": CLI_VERSION, "reasoning_effort": "low", "cost_usd": "unknown"}


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to rerun or overwrite retained study data: {OUTPUT}")
    runner = PinnedCodexCLI()
    version = runner.check()
    if version != CLI_VERSION:
        raise SystemExit(f"Codex CLI version mismatch: {version}")
    root = Path(tempfile.mkdtemp(prefix="metis-issue6-symmetric-runs-"))
    oracle_root = Path(tempfile.mkdtemp(prefix="metis-issue6-symmetric-oracle-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    atexit.register(shutil.rmtree, oracle_root, ignore_errors=True)
    global ORACLE_FILE
    ORACLE_FILE = oracle_root / "answers.json"
    rng = random.Random(SEED)
    cases = []
    answers: dict[str, str] = {}
    task_families: dict[str, list[str]] = {}
    task_index = 0
    for family in FAMILIES:
        for _instance in range(2):
            task_id = f"{TASK_PREFIX}-{task_index:02d}"
            assigned_family = list(family)
            if rng.randrange(2):
                assigned_family.reverse()
            components = (bytes(rng.choice(COMPONENT_ALPHABET) for _ in range(12)),
                          bytes(rng.choice(COMPONENT_ALPHABET) for _ in range(12)))
            answer = hashlib.sha256(components[0] + b"\0" + components[1]).hexdigest()
            task_families[task_id] = assigned_family
            assigned_pair = (assigned_family[0], assigned_family[1])
            for repetition in range(TASK_REPETITIONS):
                case_id = f"{task_id}-rep-{repetition}"
                answers[case_id] = answer
                cases.append((case_id, components, assigned_pair))
            task_index += 1
    descriptor = os.open(ORACLE_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(answers, stream, sort_keys=True)
    order_rng = random.Random(ORDER_SEED)
    trial_order = {}
    for case_id, *_ in cases:
        arms = ["single", "multi_separate", "multi_combined"]
        order_rng.shuffle(arms)
        trial_order[case_id] = arms
    session = CodexSession(root / "state" / "metis.sqlite")
    scheduler = AgentScheduler(session.database, BridgeHost(max_parallel=BUDGET["slots"]))
    records = []
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Retain only answer-free metrics. Replace atomically after every completed arm.
    for case_id, components, case_family in cases:
        for arm in trial_order[case_id]:
            record = run_arm(session, scheduler, runner, root, case_id, components, case_family, arm)
            records.append(record)
            dataset = build_dataset(records, task_families, trial_order)
            temporary = OUTPUT.with_suffix(".tmp")
            temporary.write_text(json.dumps(dataset, separators=(",", ":")), encoding="utf-8")
            temporary.replace(OUTPUT)
            print(json.dumps({"case": case_id, "arm": arm, "verified": record["oracle_verified"],
                              "completed_records": len(records), "elapsed_seconds": record["elapsed_seconds"],
                              "calls": record["calls_observed"]}, separators=(",", ":")), flush=True)
    OUTPUT.write_text(json.dumps(build_dataset(records, task_families, trial_order),
                                 sort_keys=True, indent=2) + "\n", encoding="utf-8")


def build_dataset(records: list[dict[str, Any]], task_families: dict[str, list[str]],
                  trial_order: dict[str, list[str]], *,
                  arms: tuple[str, ...] = ("single", "multi_separate", "multi_combined"),
                  study: str = STUDY_ID, seed: int = SEED, order_seed: int = ORDER_SEED) -> dict[str, Any]:
    by_key = {(row["case"], row["arm"]): row for row in records}
    comparisons = []
    for case_id in sorted({row["case"] for row in records}):
        trial = {arm: by_key.get((case_id, arm)) for arm in arms}
        if any(row is None for row in trial.values()):
            continue
        complete_trial = {arm: row for arm, row in trial.items() if row is not None}
        comparisons.append({"case": case_id, "task_id": case_id.rsplit("-rep-", 1)[0],
                           "arms": {arm: {key: complete_trial[arm][key] for key in (
                               "oracle_verified", "elapsed_seconds", "calls_observed", "calls_reserved",
                               "usage", "actions", "synthesis_complete", "job_states", "candidate_ready_jobs",
                               "decision_counts", "report_rejections", "report_rejection_categories",
                               "report_rejection_stages",
                               "terminal_reason_categories", "model_turn_budget_denials",
                               "peer_reserve_denials")}
                                    for arm in arms}})
    return {"study": study, "model": MODEL, "cli": CLI_VERSION, "reasoning_effort": "low",
            "seed": seed, "order_seed": order_seed, "distinct_tasks": len(task_families),
            "repetitions_per_task": TASK_REPETITIONS, "encoding_pairs": task_families,
            "trial_order": trial_order, "records": records, "comparisons": comparisons,
            "arms": list(arms),
            "retained_content": "answer-free metrics; no candidates, components, digests, or oracle values"}


if __name__ == "__main__":
    main()
