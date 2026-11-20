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
from typing import Any, Literal, final

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexTurn

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


@final
class ScriptedTurns:
    """Only prerecorded in-process data is accepted by the offline controller."""

    __slots__ = ("_turns", "prompts", "schemas", "timeouts")

    def __init__(self, *turns: str | CodexTurn | None):
        if any(type(turn) not in {str, CodexTurn, type(None)} for turn in turns):
            raise TypeError("offline script entries must be fixed response data")
        self._turns = iter(turns)
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any]] = []
        self.timeouts: list[float] = []

    def _next_turn(self, prompt: str, schema: dict[str, Any], timeout: float) -> CodexTurn:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        self.timeouts.append(timeout)
        output = next(self._turns, None)
        if output is None:
            raise RuntimeError("offline response script interrupted")
        if isinstance(output, CodexTurn):
            return output
        return CodexTurn(0, output, usage={"input_tokens": 10, "output_tokens": 2})


class _ScriptedBoundaryHost(FakeHost):
    """Deterministic scheduler host; it records briefs and never runs inference."""

    name = "issue6-scripted-boundary"

    def spawn(self, assignment: dict[str, Any], brief: dict[str, Any], model: Any,
              *, timeout: float = 30.0) -> str:
        job_id = f"issue6-boundary-{len(self.spawned) + 1}"
        self.jobs[job_id] = {"assignment": assignment, "brief": brief, "model": model,
                             "plan": {"after": 1, "state": "finished", "output": None},
                             "polls": 0, "started": time.time()}
        self.spawned.append(assignment["assignment_id"])
        return job_id

    def deliver_phase(self, host_job_id: str, assignment_id: str, attempt_id: str, prompt: str,
                      schema: dict[str, Any], timeout: float) -> None:
        job = self.jobs.get(host_job_id)
        if (job is None or job["brief"].get("assignment_id") != assignment_id
                or job["brief"].get("attempt_id") != attempt_id):
            raise ValueError("phase prompt did not match the dispatched scheduler attempt")
        if not 0 < timeout <= PHASE_SECONDS or len(prompt.encode("utf-8")) > 256_000:
            raise ValueError("phase prompt or deadline exceeds the bounded fake-host contract")
        job["prompt"] = prompt
        job["schema"] = json.loads(_json(schema))
        job["timeout"] = timeout

    def consume_phase(self, host_job_id: str, assignment_id: str, attempt_id: str
                      ) -> tuple[str, dict[str, Any], float]:
        job = self.jobs.get(host_job_id)
        if (job is None or job["brief"].get("assignment_id") != assignment_id
                or job["brief"].get("attempt_id") != attempt_id or job.get("consumed")):
            raise ValueError("captured phase prompt did not match one unconsumed scheduler attempt")
        prompt, schema, timeout = job.get("prompt"), job.get("schema"), job.get("timeout")
        if not isinstance(prompt, str) or not isinstance(schema, dict) or not isinstance(timeout, float):
            raise TypeError("captured phase prompt is incomplete")
        job["consumed"] = True
        return prompt, schema, timeout


def _require_scripted(runner: ScriptedTurns) -> None:
    if type(runner) is not ScriptedTurns:
        raise TypeError("offline rehearsal accepts only built-in scripted responses")


@dataclass(frozen=True)
class PhaseReceipt:
    phase: int
    assignment_id: str
    attempt_id: str
    reservation: int
    prompt_hmac: str
    brief_sha256: str
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


class _PilotReceiptPersistenceError(RuntimeError):
    """The reservation transaction could not persist its initial phase receipt."""


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
    return (instruction + " Return one JSON object with exactly the fields required by this phase. "
            + "The fixture supplies task rules and evidence. Use only this message. No tools are available.\n"
            + "Review context: " + _json(context) + "\nPublic fixture: " + artifact.decode("ascii"))


def _one_assignment(plan: dict[str, Any], artifact_ref: str | None = None) -> dict[str, Any]:
    assignments = [item for item in plan["assignments"] if item["role"] == "artifact-triage"]
    if len(assignments) != 1:
        raise RuntimeError("planner must provide one artifact-triage profile")
    assignments[0]["max_turns"] = 1
    assignments[0]["deadline_seconds"] = PHASE_SECONDS
    if artifact_ref is not None:
        assignments[0]["inputs"] = {"artifacts": [artifact_ref]}
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = ["artifact-triage"]
    plan["daybreak_covers"] = []
    return plan


def _prepare_receipts(database: Path) -> None:
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS issue6_build_pilot_receipts (
            run_id TEXT NOT NULL, phase INTEGER NOT NULL, assignment_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL, reservation INTEGER NOT NULL UNIQUE,
            payload TEXT NOT NULL, PRIMARY KEY (run_id, phase))""")


def _reconcile(database: Path, run_id: str, receipts: list[PhaseReceipt], actions: int) -> None:
    expected = [
        (
            item.reservation, item.assignment_id, item.attempt_id,
            item.assignment_id, item.attempt_id, item.phase, _json(asdict(item)),
            "completed" if item.outcome == "accepted" else "failed", int(item.outcome == "accepted"),
        )
        for item in receipts
    ]
    with sqlite3.connect(database) as db:
        recorded = db.execute("""
            SELECT turns.id, turns.assignment_id, turns.attempt_id,
                receipts.assignment_id, receipts.attempt_id, receipts.phase, receipts.payload, jobs.state,
                (SELECT COUNT(*) FROM ctf_agent_reports reports
                WHERE reports.run_id = turns.run_id AND reports.assignment_id = turns.assignment_id
                    AND reports.attempt_id = turns.attempt_id)
            FROM agent_turn_reservations turns
            JOIN agent_jobs jobs ON jobs.assignment_id = turns.assignment_id
                AND jobs.attempt_id = turns.attempt_id AND jobs.run_id = turns.run_id
            LEFT JOIN issue6_build_pilot_receipts receipts ON receipts.reservation = turns.id
                AND receipts.run_id = turns.run_id
            WHERE turns.run_id = ?
            ORDER BY turns.id
        """, (run_id,)).fetchall()
        report_count, = db.execute("SELECT COUNT(*) FROM ctf_agent_reports WHERE run_id = ?", (run_id,)).fetchone()
        receipt_count, = db.execute(
            "SELECT COUNT(*) FROM issue6_build_pilot_receipts WHERE run_id = ?", (run_id,),
        ).fetchone()
    if recorded != expected or report_count != actions or receipt_count != len(receipts):
        raise RuntimeError("pilot phase, reservation or report evidence does not reconcile")


def _ensure_dispatch_capacity(scheduler: AgentScheduler, run_id: str, required_calls: int) -> None:
    """Refuse before dispatch unless calls and a slot are available.

    This is a model-free preflight for one private pilot ledger, not an atomic slot
    lease. AgentScheduler.dispatch remains authoritative; any intervening capacity
    change must fail closed when exactly one assignment does not start.
    """
    if required_calls < 1:
        raise ValueError("pilot preflight requires a positive remaining-call count")
    budget = scheduler.model_turn_budget(run_id)
    if budget is None or budget["limit"] - budget["reserved"] < required_calls:
        raise ValueError("pilot scheduler preflight refused: insufficient model-call budget")
    settings = scheduler.config()
    slot_limit = min(settings["global_slots"], scheduler.host.capabilities().max_parallel)
    with sqlite3.connect(scheduler.database) as db:
        global_busy, = db.execute(
            "SELECT COUNT(*) FROM agent_jobs WHERE state IN ('running','unknown')",
        ).fetchone()
        run_busy, = db.execute(
            "SELECT COUNT(*) FROM agent_jobs WHERE run_id=? AND state IN ('running','unknown')",
            (run_id,),
        ).fetchone()
    if global_busy >= slot_limit or run_busy >= settings["per_run_slots"]:
        raise ValueError("pilot scheduler preflight refused: no dispatch slot is available")


def _dispatch_phase(scheduler: AgentScheduler, run_id: str, required_calls: int) -> dict[str, Any]:
    """Run the preflight immediately before dispatch and require one started assignment."""
    _ensure_dispatch_capacity(scheduler, run_id, required_calls)
    started = scheduler.dispatch(run_id)["started"]
    if len(started) != 1:
        raise RuntimeError("pilot scheduler preflight could not start exactly one phase assignment")
    return started[0]


def _charge_receipt(database: Path, run_id: str, receipt: PhaseReceipt, *, terminal: bool = False) -> None:
    with sqlite3.connect(database) as db:
        if terminal:
            prior = replace(receipt, input_tokens=None, output_tokens=None, outcome="launching")
            changed = db.execute(
                "UPDATE issue6_build_pilot_receipts SET payload=? WHERE run_id=? AND phase=? "
                "AND assignment_id=? AND attempt_id=? AND reservation=? AND payload=?",
                (_json(asdict(receipt)), run_id, receipt.phase, receipt.assignment_id, receipt.attempt_id,
                 receipt.reservation, _json(asdict(prior))),
            )
            if changed.rowcount != 1:
                raise RuntimeError("pilot launch receipt mismatch")
        else:
            _insert_receipt(db, run_id, receipt)


def _insert_receipt(db: sqlite3.Connection, run_id: str, receipt: PhaseReceipt) -> None:
    db.execute("INSERT INTO issue6_build_pilot_receipts VALUES (?,?,?,?,?,?)",
               (run_id, receipt.phase, receipt.assignment_id, receipt.attempt_id,
                receipt.reservation, _json(asdict(receipt))))


def _usage(turn: CodexTurn, key: str) -> int | None:
    value = (turn.usage or {}).get(key)
    return value if type(value) is int and value >= 0 else None


def _mac(key: bytes, domain: bytes, data: bytes) -> str:
    return hmac.digest(key, domain + b"\0" + data, "sha256").hex()


def _run_arm(directory: Path, case_id: str, fixture: BuildFixture, runner: ScriptedTurns,
             model: str, receipt_key: bytes, workflow: Workflow,
             *, clock: Callable[[], float] = time.monotonic) -> ArmResult:
    _require_scripted(runner)
    if workflow not in {"owner_note", "fresh_reviewer"}:
        raise ValueError("unknown reviewer workflow")
    directory.mkdir(mode=0o700, exist_ok=False)
    started = clock()
    database = directory / "ledger.sqlite"
    host = _ScriptedBoundaryHost(max_parallel=1)
    scheduler = AgentScheduler(database, host)
    # Scheduler initialization owns several tables; explicitly restrict the file.
    database.chmod(0o600)
    _prepare_receipts(database)
    scheduler.configure(global_slots=1, per_run_slots=1, specialist_turn_budget=MAX_PHASES,
                        catalog=[{"id": model, "tier": "standard"}], current_model=model,
                        memory_retrieval=False)
    source = directory / "public.json"
    artifact = canonical_artifact(fixture, include_submission_rule=False)
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
            run_id, mode="delegated", plan_policy=lambda plan: _one_assignment(plan, artifact_ref),
            reason="Check provisional diagnosis against the supplied observations" if phase > 1 else None,
        )
        scheduler.enqueue(run_id, wave["wave_id"])
        job = _dispatch_phase(scheduler, run_id, MAX_PHASES - phase + 1)
        assignment, attempt = job["assignment_id"], job["attempt_id"]
        brief = job["brief"]
        if (brief.get("run_id") != run_id or brief.get("assignment_id") != assignment
                or brief.get("attempt_id") != attempt or brief.get("artifacts") != [artifact_ref]):
            raise RuntimeError("scheduler phase brief did not match its run, attempt, and artifact scope")
        host_brief = host.jobs[job["host_job_id"]]["brief"]
        if host_brief != brief:
            raise RuntimeError("fake host received a different scheduler phase brief")
        prompt = _prompt(artifact, prior, workflow)
        schema = _schema(phase == 1)

        def should_stop(cutoff: float = deadline) -> bool:
            return clock() >= cutoff or scheduler.run_cancelled(run_id)

        if should_stop():
            scheduler.fail(assignment, attempt, "deadline before launch")
            break
        budget_before = scheduler.model_turn_budget(run_id)
        if budget_before is None or budget_before["reserved"] != phase - 1:
            raise RuntimeError("pilot phase must begin with exactly one reservation per prior phase")

        receipt: PhaseReceipt | None = None

        def persist_receipt(
            db: sqlite3.Connection,
            reservation_id: int,
            *,
            receipt_phase: int = phase,
            receipt_assignment: str = assignment,
            receipt_attempt: str = attempt,
            receipt_prompt: str = prompt,
            receipt_brief: dict[str, Any] = brief,
            receipt_artifact: bytes = artifact,
            receipt_schema: dict[str, Any] = schema,
        ) -> None:
            nonlocal receipt
            try:
                if receipt is not None:
                    raise RuntimeError("pilot initial receipt was persisted more than once")
                receipt = PhaseReceipt(
                    receipt_phase, receipt_assignment, receipt_attempt, reservation_id,
                    _mac(receipt_key, b"prompt", receipt_prompt.encode()),
                    hashlib.sha256(_json(receipt_brief).encode()).hexdigest(),
                    _mac(receipt_key, b"artifact", receipt_artifact),
                    hashlib.sha256(_json(receipt_schema).encode()).hexdigest(),
                    None, None, "launching",
                )
                _insert_receipt(db, run_id, receipt)
            except Exception as error:
                raise _PilotReceiptPersistenceError(
                    f"pilot initial receipt persistence failed: {error}"
                ) from error

        try:
            reserved = scheduler.reserve_model_turn(
                run_id, assignment, attempt, persist_receipt=persist_receipt,
            )
        except _PilotReceiptPersistenceError:
            try:
                scheduler.fail(assignment, attempt, "pilot reservation receipt persistence failed")
            except Exception as recovery_error:
                raise RuntimeError("pilot receipt persistence and failure recording both failed") from recovery_error
            raise
        if (reserved is None or reserved["turn"] != phase or reserved["limit"] != MAX_PHASES
                or reserved["remaining"] != MAX_PHASES - phase):
            raise RuntimeError("pilot model-call reservation mismatch")
        if receipt is None or receipt.reservation != reserved["reservation_id"]:
            raise RuntimeError("pilot atomic reservation receipt mismatch")
        timeout = deadline - clock()
        if timeout <= 0:
            receipt = replace(receipt, outcome="deadline_before_launch")
            _charge_receipt(database, run_id, receipt, terminal=True)
            receipts.append(receipt)
            scheduler.fail(assignment, attempt, "deadline after reservation")
            break
        try:
            # The scripted response consumes the exact prompt/schema captured for this
            # scheduler attempt; it has no route to a model or provider.
            host.deliver_phase(job["host_job_id"], assignment, attempt, prompt, schema, timeout)
            captured_prompt, captured_schema, captured_timeout = host.consume_phase(
                job["host_job_id"], assignment, attempt)
            if (_mac(receipt_key, b"prompt", captured_prompt.encode()) != receipt.prompt_hmac
                    or hashlib.sha256(_json(captured_schema).encode()).hexdigest() != receipt.schema_sha256
                    or captured_timeout != timeout):
                raise ValueError("captured phase input did not match its pre-dispatch receipt")
        except (TypeError, ValueError):
            receipt = replace(receipt, outcome="prompt_delivery_rejected")
            _charge_receipt(database, run_id, receipt, terminal=True)
            receipts.append(receipt)
            scheduler.fail(assignment, attempt, receipt.outcome)
            break
        try:
            turn = ScriptedTurns._next_turn(runner, captured_prompt, captured_schema, captured_timeout)
        except RuntimeError:
            receipt = replace(receipt, outcome="script_interrupted")
            _charge_receipt(database, run_id, receipt, terminal=True)
            scheduler.fail(assignment, attempt, receipt.outcome)
            raise
        diagnosis = None
        if CodexTurn.violations(turn) or turn.tool_errors:
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
    _reconcile(database, run_id, receipts, actions)
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


def run_calibration(root: Path, runner: ScriptedTurns, model: str, study_key: bytes) -> dict[str, Any]:
    """Rehearse the fixed 36-case calibration in a non-reusable private root."""
    _require_scripted(runner)
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
        case_id.encode() + b"\0" + canonical_artifact(fixture, include_submission_rule=False)
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
