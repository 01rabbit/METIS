"""Offline rehearsal and pilot-only matched review controller for Issue #6."""

import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI, CodexTurn

from .issue6_build_artifact import (
    _strict_object,
    canonical_artifact,
    fixture_labels,
    parse_proposal,
)
from .issue6_build_generator import FAMILIES, Difficulty, make_fixture
from .issue6_build_oracle import BuildFixture, Cause, verify_proposal

NOTE_BYTES = 384
PHASE_SECONDS = 60
MAX_PHASES = 2
TIERS: tuple[Difficulty, ...] = ("small", "medium", "large")
Workflow = Literal["owner_note", "fresh_reviewer"]


class PilotRunner(Protocol):
    def run(self, prompt: str, *, model: str | None, timeout: float,
            should_stop: Callable[[], bool] | None = None,
            output_schema: dict[str, Any] | None = None) -> CodexTurn: ...


@dataclass(frozen=True)
class PhaseReceipt:
    phase: int
    reservation: int
    prompt_hmac: str
    artifact_hmac: str
    schema_sha256: str
    input_tokens: int | None
    output_tokens: int | None
    outcome: str


@dataclass(frozen=True)
class ArmResult:
    case_id: str
    run_id: str
    complete: bool
    verified: bool
    actions: int
    calls_reserved: int
    oracle_checks: int
    elapsed_ms: int
    phases: tuple[PhaseReceipt, ...]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _schema(initial: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {"option_id": {"type": "string"}}
    if initial:
        properties["work_note"] = {"type": "string", "maxLength": NOTE_BYTES}
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _diagnosis(raw: str | None, fixture: BuildFixture, initial: bool) -> tuple[str, str] | None:
    if raw is None or len(raw) > 4096:
        return None
    try:
        response = json.loads(raw, object_pairs_hook=_strict_object)
        required = {"option_id", "work_note"} if initial else {"option_id"}
        if not isinstance(response, dict) or set(response) != required:
            return None
        option = response["option_id"]
        note = response.get("work_note", "")
        if not isinstance(note, str) or len(note.encode("utf-8")) > NOTE_BYTES:
            return None
        if parse_proposal(_json({"option_id": option}), fixture) is None:
            return None
        return option, note
    except (ValueError, RecursionError):
        return None


def _prompt(artifact: bytes, prior: tuple[str, str] | None, workflow: Workflow) -> str:
    if prior is None:
        instruction = ("Diagnose the build using the supplied runbook and evidence. Return option_id "
                       "and a private work_note of at most 384 UTF-8 bytes for review.")
        context: dict[str, str] = {}
    else:
        instruction = ("Review the provisional diagnosis against the same evidence. Return the "
                       "final option_id, correcting the provisional option if needed.")
        context = {"provisional_option_id": prior[0]}
        if workflow == "owner_note":
            context["prior_work_note"] = prior[1]
    return (instruction + " Follow the phase output schema; the fixture supplies task rules and evidence. "
            + "Use only this message. No tools are available.\n"
            + "Review context: " + _json(context) + "\nPublic fixture: " + artifact.decode("ascii"))


def _one_assignment(plan: dict[str, Any]) -> dict[str, Any]:
    assignments = [item for item in plan["assignments"] if item["role"] == "artifact-triage"]
    if len(assignments) != 1:
        raise RuntimeError("planner must provide one artifact-triage profile")
    assignments[0]["max_turns"] = 1
    assignments[0]["deadline_seconds"] = PHASE_SECONDS
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = ["artifact-triage"]
    plan["daybreak_covers"] = []
    return plan


def _charge_receipt(database: Path, run_id: str, receipt: PhaseReceipt, *, terminal: bool = False) -> None:
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS issue6_build_pilot_receipts (
            run_id TEXT NOT NULL, phase INTEGER NOT NULL, reservation INTEGER NOT NULL UNIQUE,
            payload TEXT NOT NULL, PRIMARY KEY (run_id, phase))""")
        if terminal:
            prior = replace(receipt, input_tokens=None, output_tokens=None, outcome="launching")
            changed = db.execute(
                "UPDATE issue6_build_pilot_receipts SET payload=? WHERE run_id=? AND phase=? "
                "AND reservation=? AND payload=?",
                (_json(asdict(receipt)), run_id, receipt.phase, receipt.reservation, _json(asdict(prior))),
            )
            if changed.rowcount != 1:
                raise RuntimeError("pilot launch receipt mismatch")
        else:
            db.execute("INSERT INTO issue6_build_pilot_receipts VALUES (?,?,?,?)",
                       (run_id, receipt.phase, receipt.reservation, _json(asdict(receipt))))


def _usage(turn: CodexTurn, key: str) -> int | None:
    value = (turn.usage or {}).get(key)
    return value if type(value) is int and value >= 0 else None


def _mac(key: bytes, domain: bytes, data: bytes) -> str:
    return hmac.digest(key, domain + b"\0" + data, "sha256").hex()


def _run_arm(directory: Path, case_id: str, fixture: BuildFixture, runner: PilotRunner,
             model: str, receipt_key: bytes, workflow: Workflow,
             *, clock: Callable[[], float] = time.monotonic) -> ArmResult:
    if workflow not in {"owner_note", "fresh_reviewer"}:
        raise ValueError("unknown reviewer workflow")
    directory.mkdir(mode=0o700, exist_ok=False)
    started = clock()
    database = directory / "ledger.sqlite"
    scheduler = AgentScheduler(database, BridgeHost())
    # Scheduler initialization owns several tables; explicitly restrict the file.
    database.chmod(0o600)
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=MAX_PHASES,
                        catalog=[{"id": model, "tier": "standard"}], current_model=model,
                        memory_retrieval=False)
    source = directory / "public.json"
    artifact = canonical_artifact(fixture)
    source.write_bytes(artifact)
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic build diagnosis", description="Diagnose a synthetic build.",
                            paths=[source], categories=["misc"], max_actions=MAX_PHASES,
                            wall_seconds=PHASE_SECONDS * MAX_PHASES, evaluation_split="practice")["run_id"]
    source.unlink()
    artifact_ref, = session.context(run_id)["challenge"]["artifacts"]
    snap = session.artifact_root(run_id) / artifact_ref
    if snap.read_bytes() != artifact:
        raise RuntimeError("intake artifact mismatch")
    # The prompt already has the only artifact; retain no recoverable fixture in the ledger root.
    snap.unlink()
    receipts: list[PhaseReceipt] = []
    prior = None
    actions = 0
    checks = 0
    verified = False
    for phase in range(1, MAX_PHASES + 1):
        phase_start = started if phase == 1 else clock()
        deadline = min(started + PHASE_SECONDS * MAX_PHASES, phase_start + PHASE_SECONDS)
        wave = scheduler.ledger.create_wave(
            run_id, mode="delegated", plan_policy=_one_assignment,
            reason="Check provisional diagnosis against the supplied observations" if phase > 1 else None,
        )
        scheduler.enqueue(run_id, wave["wave_id"])
        job, = scheduler.dispatch(run_id)["started"]
        assignment, attempt = job["assignment_id"], job["attempt_id"]
        prompt = _prompt(artifact, prior, workflow)
        schema = _schema(phase == 1)

        def should_stop(cutoff: float = deadline) -> bool:
            return clock() >= cutoff or scheduler.run_cancelled(run_id)

        if should_stop():
            scheduler.fail(assignment, attempt, "deadline before launch")
            break
        reserved = scheduler.reserve_model_turn(run_id, assignment, attempt)
        if reserved is None or reserved["turn"] != phase:
            raise RuntimeError("pilot model-call reservation mismatch")
        receipt = PhaseReceipt(
            phase, reserved["reservation_id"], _mac(receipt_key, b"prompt", prompt.encode()),
            _mac(receipt_key, b"artifact", artifact), hashlib.sha256(_json(schema).encode()).hexdigest(),
            None, None, "launching",
        )
        _charge_receipt(database, run_id, receipt)
        timeout = deadline - clock()
        if timeout <= 0:
            receipt = replace(receipt, outcome="deadline_before_launch")
            _charge_receipt(database, run_id, receipt, terminal=True)
            receipts.append(receipt)
            scheduler.fail(assignment, attempt, "deadline after reservation")
            break
        turn = runner.run(prompt, model=model, timeout=timeout, should_stop=should_stop, output_schema=schema)
        if isinstance(runner, CodexCLI) and turn.isolation.get("mode") != "seatbelt":
            raise RuntimeError("pilot Codex turn lacks the required Seatbelt boundary")
        diagnosis = None
        if turn.violations() or turn.tool_errors:
            outcome = "tool_policy"
        elif turn.timed_out or turn.stopped or should_stop():
            outcome = "deadline_or_cancelled"
        elif turn.returncode != 0:
            outcome = "runtime_failure"
        else:
            diagnosis = _diagnosis(turn.message, fixture, phase == 1)
            outcome = "accepted" if diagnosis is not None else "invalid_response"
        receipt = replace(receipt, input_tokens=_usage(turn, "input_tokens"),
                          output_tokens=_usage(turn, "output_tokens"), outcome=outcome)
        _charge_receipt(database, run_id, receipt, terminal=True)
        receipts.append(receipt)
        if diagnosis is None:
            if not scheduler.run_cancelled(run_id):
                scheduler.fail(assignment, attempt, outcome)
            break
        scheduler.complete(run_id, assignment, attempt, {
            "hypothesis": "The phase supplied a structured option.",
            "evidence": "The structured submission passed format validation.",
            "falsifier": "Final verification can reject the submitted option.",
            "next_action": ("Review the provisional structured option." if phase == 1
                            else "Finalize the reviewed structured option."),
            "event_sequences": [0],
            "status": "inconclusive",
        })
        actions += 1
        if should_stop():
            break
        if phase == 1:
            prior = diagnosis
        else:
            proposal = parse_proposal(_json({"option_id": diagnosis[0]}), fixture)
            if proposal is None:
                raise RuntimeError("validated phase option unexpectedly missing")
            checks += 1
            verified = verify_proposal(fixture, proposal)
            if should_stop():
                verified = False
    budget = scheduler.model_turn_budget(run_id)
    if budget is None or budget["reserved"] != len(receipts):
        raise RuntimeError("pilot model-call receipts do not reconcile")
    complete = actions == MAX_PHASES and checks == 1 and not should_stop()
    return ArmResult(case_id, run_id, complete, complete and verified, actions, budget["reserved"],
                     checks, round((clock() - started) * 1000), tuple(receipts))


def _has_distinct_dags(fixtures: list[tuple[Difficulty, BuildFixture]]) -> bool:
    dags = {
        tuple(sorted((job.name, tuple(sorted(job.deps))) for job in fixture.jobs))
        for _, fixture in fixtures
    }
    return len(dags) == len(fixtures)


def _direct_slow_baseline(fixture: BuildFixture) -> Cause | None:
    """Single-log arithmetic baseline. Abstain unless one slow job is directly observed."""
    logs = {(row.job, row.event): row.tick for row in fixture.observations}
    matches = []
    for job in fixture.jobs:
        start = logs.get((job.name, "start"))
        finish = logs.get((job.name, "finish"))
        if start is None or finish is None:
            continue
        implied = Cause("slow_job", job.name, finish - start - job.duration)
        if implied in fixture.options:
            matches.append(implied)
    return matches[0] if len(matches) == 1 else None


def run_calibration(root: Path, runner: PilotRunner, model: str, study_key: bytes) -> dict[str, Any]:
    """Rehearse the fixed 36-case calibration in a non-reusable private root."""
    if isinstance(runner, CodexCLI):
        raise TypeError("real pilot launch is disabled pending review of execution admission")
    if len(study_key) < 32:
        raise ValueError("study key requires at least 32 private bytes")
    root.mkdir(mode=0o700, exist_ok=False)
    fixtures: list[tuple[Difficulty, BuildFixture]] = []
    aggregate: list[dict[str, Any]] = []
    for tier in TIERS:
        tier_fixtures = []
        for family in FAMILIES:
            stats: dict[str, Any] = {"tier": tier, "family": family, "admitted": 0, "ambiguous": 0,
                     "missing_observations": 0, "baseline_attempted": 0, "baseline_verified": 0}
            for index in range(4):
                seed = int(_mac(study_key, b"pilot-seed", f"{tier}:{family}:{index}".encode()), 16)
                admission = make_fixture(seed, tier, family)
                tier_fixtures.append((tier, admission.fixture))
                stats["admitted"] += 1
                stats["ambiguous"] += admission.ambiguous
                stats["missing_observations"] += admission.incompatible
                baseline = _direct_slow_baseline(admission.fixture)
                if baseline is not None:
                    stats["baseline_attempted"] += 1
                    stats["baseline_verified"] += int(verify_proposal(admission.fixture, baseline))
            aggregate.append(stats)
        ordering = int(_mac(study_key, b"pilot-order", tier.encode()), 16)
        random.Random(ordering).shuffle(tier_fixtures)
        fixtures.extend(tier_fixtures)
    fixture_labels(fixture for _, fixture in fixtures)
    if not _has_distinct_dags(fixtures):
        raise ValueError("calibration contains a repeated jobs DAG")
    case_ids = [secrets.token_hex(16) for _ in fixtures]
    commitment = _mac(study_key, b"calibration", b"\n".join(
        case_id.encode() + b"\0" + canonical_artifact(fixture)
        for case_id, (_, fixture) in zip(case_ids, fixtures, strict=True)
    ))
    (root / "claim.json").write_text(_json({"commitment": commitment, "model": model, "cases": case_ids}))
    rows = []
    for case_id, (tier, fixture) in zip(case_ids, fixtures, strict=True):
        result = _run_arm(root / case_id, case_id, fixture, runner, model, study_key, "owner_note")
        row = {"tier": tier, **asdict(result)}
        rows.append(row)
        with (root / "progress.jsonl").open("a", encoding="utf-8") as report:
            report.write(_json(row) + "\n")
            report.flush()
        if any(receipt.outcome == "tool_policy" for receipt in result.phases):
            raise RuntimeError("tool-policy failure halts calibration")
    selected = None
    for tier in TIERS:
        tier_rows = [row for row in rows if row["tier"] == tier]
        if sum(row["complete"] for row in tier_rows) >= 10 and 4 <= sum(row["verified"] for row in tier_rows) <= 9:
            selected = tier
            break
    summary = {"commitment": commitment, "model": model, "selected_tier": selected,
               "generator_diagnostics": aggregate, "rows": rows}
    with (root / "completed.json").open("x", encoding="utf-8") as output:
        output.write(_json(summary) + "\n")
    return summary
