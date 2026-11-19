"""Held-out token claims bind to the real scheduler row without model execution."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexTurn, _decision, final_handoff_schema, run_assignment
from metis.core.contracts import RunStatus
from metis.core.ctf_orchestration import AgentLedger
from metis.core.llama_server_backend import LlamaBackendError, LlamaBackendRefused
from metis.core.llama_specialist import LlamaSpecialist
from metis.core.study_token_admission import StudyTokenAdmission, TokenLaunchOutcome
from metis.evaluation.heldout_protocol import Protocol, bind_run, digest, schedule

PROMPT_PREFIX = "Use bounded METIS tools and return evidence only."


def test_optional_native_manifest_preserves_v1_digest_when_absent(tmp_path):
    protocol = _protocol(tmp_path / "state.sqlite", manifest=None)
    legacy_payload = protocol.model_dump(mode="json")
    legacy_payload["llama_backend"].pop("native_manifest_sha256")
    legacy_digest = hashlib.sha256(json.dumps(
        legacy_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()
    assert digest(protocol) == legacy_digest


def _count_if_table_exists(db: sqlite3.Connection, table: str) -> int:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return 0
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _protocol(database: Path, *, manifest: str | None = "d" * 64,
              run_tokens: int = 10_000) -> Protocol:
    arms = ["full", "single_agent"]
    budget = {"model_calls": 4, "tokens": run_tokens, "actions": 20,
              "seconds": 60.0, "cost_usd": None}
    prompt_sha256 = hashlib.sha256(PROMPT_PREFIX.encode()).hexdigest()
    return Protocol.model_validate({
        "schema_version": 1, "study_id": "scheduler-admission-test", "measurement": "real_model",
        "model_pin": "test-model", "runtime_pin": "bridge", "seed": 1,
        "repetitions": 2, "arms": arms, "baseline": "full",
        "budgets": {arm: budget for arm in arms},
        "tasks": [{"task_id": f"task{i}", "source_id": f"source{i}",
                    "distribution_sha256": f"{i + 1:064x}", "category": "rev",
                    "difficulty": "easy", "split": "held_out", "exposure": "unseen",
                    "solvability_control_verified": True} for i in range(2)],
        "arm_config": {
            "full": {"memory_enabled": True, "planner_enabled": True,
                     "max_specialists": 4, "prompt_sha256": prompt_sha256},
            "single_agent": {"memory_enabled": True, "planner_enabled": True,
                              "max_specialists": 1, "prompt_sha256": prompt_sha256},
        },
        "llama_backend": {
            "binary_sha256": "b" * 64, "model_sha256": "c" * 64,
            "native_manifest_sha256": manifest,
            "database_path": str(database.resolve()), "budget_key": "shared-study",
            "token_limit": min(80_000, 8 * run_tokens),
            "max_output_tokens": 2, "context_reservation": True,
        },
    })


def _running_slot(tmp_path: Path, *, protocol: Protocol | None = None):
    database = tmp_path / "state.sqlite"
    selected_protocol = protocol or _protocol(database)
    artifacts = [tmp_path / "sample.txt", tmp_path / "notes.txt"]
    artifacts[0].write_text("synthetic fixture", encoding="utf-8")
    artifacts[1].write_text("synthetic notes", encoding="utf-8")
    run = CodexSession(database).intake(
        title="Synthetic held-out fixture", description="Inspect a deterministic local text sample.",
        paths=artifacts, categories=["crypto", "forensics"], max_actions=20, wall_seconds=60,
        evaluation_split="heldout",
    )
    slot = next(item for item in schedule(selected_protocol) if item["arm"] == "full")
    bind_run(selected_protocol, database, run["run_id"], **slot,
             expected_sha256=digest(selected_protocol), prompt_text=PROMPT_PREFIX)
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run["run_id"])
    scheduler = AgentScheduler(database, BridgeHost())
    scheduler.configure(current_model="test-model", catalog=[])
    scheduler.enqueue(run["run_id"], wave["wave_id"])
    dispatched = scheduler.dispatch(run["run_id"])
    started = dispatched["started"]
    assert started, dispatched
    job = started[0]
    return database, scheduler, selected_protocol, run["run_id"], job


def _terminalize(session: CodexSession, run_id: str, status: RunStatus) -> None:
    if status == RunStatus.SOLVED:
        session._emit(run_id, RunStatus.EXECUTING)
        session._emit(run_id, RunStatus.OBSERVING)
        session._emit(run_id, RunStatus.VERIFYING)
        session._emit(run_id, RunStatus.SOLVED)
    elif status == RunStatus.EXHAUSTED:
        session._emit(run_id, RunStatus.EXHAUSTED, reason="budget_limit")
    else:
        raise AssertionError(f"unsupported test terminal status: {status}")


class AdmittedFakeRunner(LlamaSpecialist):

    def __init__(self, database: Path, *, fail: bool = False):
        super().__init__(model_id="test-model", binary=Path("/synthetic/server"),
                         binary_sha256="b" * 64, model_path=Path("/synthetic/model.gguf"),
                         model_sha256="c" * 64, database=database, budget_key="shared-study",
                         token_limit=80_000, max_output_tokens=2, context_reservation=True,
                         native_manifest_sha256="d" * 64)
        self.hard_token_budget_enforced = True
        self.calls: list[tuple[str, object]] = []
        self.fail = fail

    def run(self, _prompt, *, model=None, timeout=1, should_stop=None, images=None, output_schema=None):
        raise AssertionError("native admitted fixture must use run_admitted")

    def run_admitted(self, prompt, *, token_claim, **_kwargs):
        self.calls.append((prompt, token_claim))
        if self.fail:
            raise TimeoutError("synthetic runner interruption")
        return CodexTurn(returncode=0, message=json.dumps({
            "action": "fail", "intent": None, "report": None,
            "reason": "The synthetic run stops without a candidate.", "candidate": None,
        }), thread_id="fixture", usage={"input_tokens": 1, "output_tokens": 1},
            item_types=["agent_message"])


def test_run_assignment_claims_actual_reservation_and_hashes_exact_prompt(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    runner = AdmittedFakeRunner(database)

    run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                   study_token_admission=admission, final_handoff_call_limit=1)

    assert len(runner.calls) == 1
    prompt, claim = runner.calls[0]
    assert PROMPT_PREFIX + "\n\n" in prompt
    assert "FINAL SPECIALIST CALL:" in prompt
    assert claim.receipt.attempt.prompt_sha256 == hashlib.sha256(prompt.encode()).hexdigest()
    assert claim.receipt.study.native_manifest_sha256 == "d" * 64
    assert claim.receipt.attempt.tokens == 4098  # Conservative reservation, not measured usage.
    with sqlite3.connect(database) as db:
        reservation = db.execute(
            "SELECT id FROM agent_turn_reservations WHERE run_id=? AND assignment_id=?",
            (run_id, job["assignment_id"]),
        ).fetchone()[0]
        assert claim.receipt.attempt.turn_reservation_id == reservation
        detail = json.loads(db.execute(
            "SELECT detail FROM agent_job_log WHERE assignment_id=? AND event='heldout_prompt_applied'",
            (job["assignment_id"],),
        ).fetchone()[0])
        assert detail["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        assert db.execute("SELECT COUNT(*) FROM study_token_launches").fetchone()[0] == 1
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (1,)
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone()[0] == 4098
        stored_text = " ".join(str(value) for row in db.execute(
            "SELECT payload FROM heldout_arm_bindings UNION ALL "
            "SELECT detail FROM agent_job_log UNION ALL SELECT prompt_sha256 FROM study_token_attempts"
        ) for value in row)
        assert prompt not in stored_text


def test_run_assignment_native_consumer_hashes_exact_bytes_sent_to_backend(tmp_path, monkeypatch):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    pin = protocol.llama_backend
    runner = LlamaSpecialist(model_id=protocol.model_pin, binary=tmp_path / "server",
        binary_sha256=pin.binary_sha256, model_path=tmp_path / "model.gguf",
        model_sha256=pin.model_sha256, database=database, budget_key=pin.budget_key,
        token_limit=pin.token_limit, max_output_tokens=pin.max_output_tokens,
        context_reservation=True, native_manifest_sha256=pin.native_manifest_sha256)
    requests = []
    class FakeBackend:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, prompt, **_kwargs):
            requests.append(prompt)
            return (json.dumps({"action": "fail", "intent": None, "report": None,
                                "reason": "synthetic", "candidate": None}), 100, 1)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)

    run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                   study_token_admission=admission, final_handoff_call_limit=1)

    assert len(requests) == 1
    request_digest = hashlib.sha256(requests[0].encode()).hexdigest()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT prompt_sha256 FROM study_token_attempts").fetchone() == (request_digest,)
        assert db.execute("SELECT status FROM study_token_outcomes").fetchone() == ("completed",)


def test_driver_handles_deep_invalid_native_json_after_recording_usage(tmp_path, monkeypatch):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    pin = protocol.llama_backend
    runner = LlamaSpecialist(model_id=protocol.model_pin, binary=tmp_path / "server",
        binary_sha256=pin.binary_sha256, model_path=tmp_path / "model.gguf",
        model_sha256=pin.model_sha256, database=database, budget_key=pin.budget_key,
        token_limit=pin.token_limit, max_output_tokens=pin.max_output_tokens,
        context_reservation=True, native_manifest_sha256=pin.native_manifest_sha256)
    deep_json = '{"action":"report","report":{"body":' + "[" * 20_000 + "0" + "]" * 20_000 + "}}"
    with pytest.raises(RecursionError):
        _decision(deep_json)
    class FakeBackend:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, _prompt, **_kwargs):
            return deep_json, 100, 1
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    result = run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                            study_token_admission=admission, final_handoff_call_limit=1)
    assert result["job_state"] == "failed"
    assert any("recursion" in json.dumps(item).lower() for item in result["intents"])
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status,observed_work FROM study_token_outcomes").fetchone() == (
            "completed", 101,
        )


@pytest.mark.parametrize(("failure", "expected"), [
    ("deadline", "timeout"), ("usage", "server_error"), ("refused", "launch_failed"),
])
def test_admitted_backend_failures_record_terminal_and_cannot_retry(tmp_path, monkeypatch, failure, expected):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    pin = protocol.llama_backend
    runner = LlamaSpecialist(model_id=protocol.model_pin, binary=tmp_path / "server",
        binary_sha256=pin.binary_sha256, model_path=tmp_path / "model.gguf",
        model_sha256=pin.model_sha256, database=database, budget_key=pin.budget_key,
        token_limit=pin.token_limit, max_output_tokens=pin.max_output_tokens,
        context_reservation=True, native_manifest_sha256=pin.native_manifest_sha256)
    native_calls = []
    native_requests = []
    claim_box = []
    original_claim = admission.claim_scheduler_native_launch
    def capture_claim(claim, *, owner_id):
        claim_box.append(claim)
        return original_claim(claim, owner_id=owner_id)
    monkeypatch.setattr(admission, "claim_scheduler_native_launch", capture_claim)
    class FakeBackend:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, prompt, **kwargs):
            native_calls.append(1)
            native_requests.append(prompt)
            if failure == "refused":
                raise LlamaBackendRefused("prompt exceeds reserved context")
            reason = "model call deadline exceeded" if failure == "deadline" else "completion usage mismatch"
            raise LlamaBackendError(reason)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                   study_token_admission=admission, final_handoff_call_limit=1)
    assert len(native_calls) == 1 and len(claim_box) == 1
    claim = claim_box[0]
    request = native_requests[0]
    with sqlite3.connect(database) as db:
        stored_hash = db.execute("SELECT prompt_sha256 FROM study_token_attempts").fetchone()[0]
        assert db.execute("SELECT status FROM study_token_outcomes").fetchone() == (expected,)
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone() == (4098,)
        assert db.execute("SELECT COUNT(*) FROM study_token_attempts").fetchone() == (1,)
        assert db.execute("SELECT observed_work FROM study_token_outcomes").fetchone() == (
            None,
        )
        if expected == "server_error":
            assert db.execute("SELECT exit_status FROM study_token_outcomes").fetchone() == (None,)
    assert hashlib.sha256(request.encode()).hexdigest() == stored_hash
    # The exact committed bytes are rejected after a terminal outcome, before
    # any second backend launch.
    retry = runner.run_admitted(request, model=protocol.model_pin, timeout=5,
        token_claim=claim, admission=admission, output_schema=final_handoff_schema())
    assert retry.returncode == 1 and len(native_calls) == 1


def test_concurrent_native_consumers_start_backend_once(tmp_path, monkeypatch):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    body = PROMPT_PREFIX + "\n\nsynthetic task"
    prompt = LlamaSpecialist.build_native_request(body)
    claims = []
    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id, prompt=prompt,
        ))
    scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"],
                                 persist_receipt=persist)
    claim = claims[0]
    admission.consume_scheduler_launch_claim(claim)
    pin = protocol.llama_backend
    runner = LlamaSpecialist(model_id=protocol.model_pin, binary=tmp_path / "server",
        binary_sha256=pin.binary_sha256, model_path=tmp_path / "model.gguf",
        model_sha256=pin.model_sha256, database=database, budget_key=pin.budget_key,
        token_limit=pin.token_limit, max_output_tokens=pin.max_output_tokens,
        context_reservation=True, native_manifest_sha256=pin.native_manifest_sha256)
    native_calls = []
    class FakeBackend:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, _prompt, **_kwargs):
            native_calls.append(1)
            return (json.dumps({"action": "fail", "intent": None, "report": None,
                                "reason": "synthetic", "candidate": None}), 100, 1)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    def invoke():
        return runner.run_admitted(prompt, model=protocol.model_pin, timeout=5,
                                   token_claim=claim, admission=admission)
    with ThreadPoolExecutor(max_workers=2) as pool:
        turns = [future.result(timeout=10) for future in
                 [pool.submit(invoke), pool.submit(invoke)]]
    assert sum(turn.returncode == 0 for turn in turns) == 1
    assert len(native_calls) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status FROM study_token_outcomes").fetchone() == ("completed",)


def test_same_launch_owner_rechecks_scheduler_after_cancellation(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    prompt = LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task")
    claims = []
    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id, prompt=prompt,
        ))
    scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"],
                                 persist_receipt=persist)
    claim = claims[0]
    admission.consume_scheduler_launch_claim(claim)
    owner = "f" * 32
    assert admission.claim_scheduler_native_launch(claim, owner_id=owner) == "claimed"
    scheduler.session.cancel(run_id)
    assert scheduler.jobs(run_id)[0]["state"] == "running"
    assert admission.claim_scheduler_native_launch(claim, owner_id=owner) == "stale"
    admission.record_outcome(claim, TokenLaunchOutcome(
        status="cancelled", native_manifest_sha256=claim.receipt.study.native_manifest_sha256,
    ))
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status FROM study_token_outcomes").fetchone() == ("cancelled",)


def test_native_binding_cannot_fall_back_to_ordinary_runner(tmp_path):
    _database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)

    class OrdinaryRunner:
        hard_token_budget_enforced = True

        def __init__(self):
            self.calls = 0

        def run(self, *_args, **_kwargs):
            self.calls += 1
            pytest.fail("native held-out binding must not use runner.run")

    runner = OrdinaryRunner()
    with pytest.raises(ValueError, match="pinned LlamaSpecialist"):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner)
    assert runner.calls == 0
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0


def test_native_admitted_runner_with_noop_validator_is_rejected_before_reservation(tmp_path):
    _database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)

    class UnpinnedAdmittedRunner:
        hard_token_budget_enforced = True

        def assert_heldout_binding(self, *_args, **_kwargs):
            pass

        def __init__(self):
            self.calls = 0

        def run_admitted(self, *_args, **_kwargs):
            self.calls += 1
            pytest.fail("runner without pin validation must not launch")

    runner = UnpinnedAdmittedRunner()
    with pytest.raises(ValueError, match="pinned LlamaSpecialist"):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                       study_token_admission=StudyTokenAdmission(_database))
    assert runner.calls == 0
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0


def test_llama_specialist_cannot_bypass_admission_with_ordinary_run(tmp_path):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    pin = protocol.llama_backend
    runner = LlamaSpecialist(
        model_id=protocol.model_pin, binary=tmp_path / "server", binary_sha256=pin.binary_sha256,
        model_path=tmp_path / "model.gguf", model_sha256=pin.model_sha256,
        database=database, budget_key=pin.budget_key, token_limit=pin.token_limit,
        max_output_tokens=pin.max_output_tokens, context_reservation=pin.context_reservation,
        native_manifest_sha256=pin.native_manifest_sha256,
    )
    assert not runner.hard_token_budget_enforced
    assert callable(getattr(runner, "run_admitted", None))
    with pytest.raises(ValueError, match="token-admitted runner"):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner)
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0


def test_runner_timeout_keeps_scheduler_and_study_charges(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    runner = AdmittedFakeRunner(database, fail=True)
    with pytest.raises(TimeoutError, match="synthetic runner interruption"):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                       study_token_admission=admission)
    assert len(runner.calls) == 1
    assert scheduler.model_turn_budget(run_id)["reserved"] == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone()[0] == 4098


def test_consumed_claim_stopped_before_native_consumer_records_cancelled(tmp_path, monkeypatch):
    database, scheduler, protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    capture = AdmittedFakeRunner(database)
    run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], capture,
                   study_token_admission=admission, final_handoff_call_limit=1)
    prompt, claim = capture.calls[0]
    scheduler.cancel_run(run_id)
    pin = protocol.llama_backend
    native = LlamaSpecialist(model_id=protocol.model_pin, binary=tmp_path / "server",
        binary_sha256=pin.binary_sha256, model_path=tmp_path / "model.gguf",
        model_sha256=pin.model_sha256, database=database, budget_key=pin.budget_key,
        token_limit=pin.token_limit, max_output_tokens=pin.max_output_tokens,
        context_reservation=True, native_manifest_sha256=pin.native_manifest_sha256)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend",
                        lambda **_kwargs: pytest.fail("stopped run must not launch"))
    turn = native.run_admitted(prompt, model=protocol.model_pin, timeout=5,
                               token_claim=claim, admission=admission,
                               output_schema=final_handoff_schema())
    assert turn.stopped and turn.returncode == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status FROM study_token_outcomes").fetchone() == ("cancelled",)
        assert db.execute("SELECT COUNT(*) FROM study_token_launches").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM study_token_outcomes").fetchone()[0] == 1


def test_scheduler_claim_is_single_use_under_replay_and_concurrent_claims(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    reservation = scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"])
    prompt = LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task")
    barrier = Barrier(2)

    def claim_once() -> str:
        barrier.wait(timeout=5)
        with sqlite3.connect(database, timeout=5, isolation_level=None) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                claim = StudyTokenAdmission(database).reserve_and_claim_scheduler_turn(
                    db, run_id=run_id, assignment_id=job["assignment_id"],
                    attempt_id=job["attempt_id"], reservation_id=reservation["reservation_id"],
                    prompt=prompt,
                )
                db.execute("COMMIT")
                return claim.nonce
            except ValueError as exc:
                db.execute("ROLLBACK")
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result(timeout=10) for future in [pool.submit(claim_once), pool.submit(claim_once)]]
    assert sum(outcome.startswith("model turn already has a token receipt") for outcome in outcomes) == 1
    assert sum(len(outcome) == 32 for outcome in outcomes) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM study_token_attempts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM study_token_launches").fetchone()[0] == 1


def test_launch_claim_consumption_is_atomic_and_single_use(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    scheduler.reserve_model_turn(
        run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
    )
    claim = claims[0]
    forged_attempt = claim.receipt.attempt.model_copy(update={"tokens": claim.receipt.attempt.tokens + 1})
    forged_receipt = claim.receipt.model_copy(update={"attempt": forged_attempt})
    with pytest.raises(ValueError, match="invalid or already consumed"):
        admission.consume_scheduler_launch_claim(claim.model_copy(update={"receipt": forged_receipt}))
    forged_study = claim.receipt.study.model_copy(update={"study_id": "other-study"})
    forged_receipt = claim.receipt.model_copy(update={"study": forged_study})
    with pytest.raises(ValueError, match="invalid or already consumed"):
        admission.consume_scheduler_launch_claim(claim.model_copy(update={"receipt": forged_receipt}))
    barrier = Barrier(2)

    def consume_once() -> bool:
        barrier.wait(timeout=5)
        try:
            admission.consume_scheduler_launch_claim(claim)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        consumed = [future.result(timeout=10) for future in
                    [pool.submit(consume_once), pool.submit(consume_once)]]
    assert consumed.count(True) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (1,)
    with pytest.raises(ValueError, match="already consumed"):
        admission.consume_scheduler_launch_claim(claim)


def test_scheduler_claim_refuses_consumption_after_attempt_stops(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    scheduler.reserve_model_turn(
        run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
    )
    claim = claims[0]
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET state='failed' WHERE assignment_id=?",
                   (job["assignment_id"],))
    with pytest.raises(ValueError, match="no longer the claimed running attempt"):
        admission.consume_scheduler_launch_claim(claim)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (0,)
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone()[0] == 4098


def test_scheduler_claim_refuses_consumption_after_run_cancellation(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    scheduler.reserve_model_turn(
        run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
    )
    claim = claims[0]
    CodexSession(database).cancel(run_id)
    with pytest.raises(ValueError, match="run is missing or not active"):
        admission.consume_scheduler_launch_claim(claim)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (0,)
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone()[0] == 4098


@pytest.mark.parametrize("terminal_status", [RunStatus.SOLVED, RunStatus.EXHAUSTED])
def test_scheduler_claim_refuses_consumption_after_run_terminalization(tmp_path, terminal_status):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    scheduler.reserve_model_turn(
        run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
    )
    claim = claims[0]
    session = CodexSession(database)
    _terminalize(session, run_id, terminal_status)
    with pytest.raises(ValueError, match="run is missing or not active"):
        admission.consume_scheduler_launch_claim(claim)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (0,)
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone()[0] == 4098


@pytest.mark.parametrize("terminal_status", [RunStatus.SOLVED, RunStatus.EXHAUSTED])
def test_scheduler_reservation_refuses_terminal_run_without_charging(tmp_path, terminal_status):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    _terminalize(CodexSession(database), run_id, terminal_status)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    with pytest.raises(ValueError, match="run is missing or not active"):
        scheduler.reserve_model_turn(
            run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
        )
    assert claims == []
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                          (run_id,)).fetchone()[0] == 0
        assert _count_if_table_exists(db, "study_token_attempts") == 0
        assert _count_if_table_exists(db, "study_token_launches") == 0


def test_scheduler_claim_rejects_slot_with_mismatched_study_id(tmp_path):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db, run_id=run_id, assignment_id=job["assignment_id"],
            attempt_id=job["attempt_id"], reservation_id=reservation_id,
            prompt=LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task"),
        ))

    scheduler.reserve_model_turn(
        run_id, job["assignment_id"], job["attempt_id"], persist_receipt=persist,
    )
    claim = claims[0]
    other_study = "forged-study"
    alternate_protocol = hashlib.sha256(b"other study protocol").hexdigest()
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        pin = db.execute(
            "SELECT runtime_sha256,model_sha256,token_limit,native_manifest_sha256 "
            "FROM study_token_pins WHERE study_id=?", (claim.receipt.study.study_id,),
        ).fetchone()
        db.execute(
            "INSERT INTO study_token_pins(study_id,protocol_sha256,runtime_sha256,model_sha256,"
            "token_limit,native_manifest_sha256) VALUES(?,?,?,?,?,?)",
            (other_study, alternate_protocol, *pin),
        )
        db.execute("UPDATE study_token_slots SET study_id=? WHERE run_id=?", (other_study, run_id))
    with pytest.raises(ValueError, match="invalid or already consumed"):
        admission.consume_scheduler_launch_claim(claim)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT consumed FROM study_token_launches").fetchone() == (0,)


@pytest.mark.parametrize("defect", ["assignment", "attempt", "reservation", "prompt"])
def test_forged_scheduler_admission_rejected_inside_reservation_transaction(tmp_path, defect):
    database, scheduler, _protocol, run_id, job = _running_slot(tmp_path)
    admission = StudyTokenAdmission(database)
    prompt = LlamaSpecialist.build_native_request(PROMPT_PREFIX + "\n\nsynthetic task")
    claims = []

    def persist(db, reservation_id):
        claims.append(admission.reserve_and_claim_scheduler_turn(
            db,
            run_id=run_id,
            assignment_id=("forged" if defect == "assignment" else job["assignment_id"]),
            attempt_id=("forged" if defect == "attempt" else job["attempt_id"]),
            reservation_id=(reservation_id + 1 if defect == "reservation" else reservation_id),
            prompt=(LlamaSpecialist.build_native_request("forged prefix\n\nsynthetic task")
                    if defect == "prompt" else prompt),
        ))

    with pytest.raises(ValueError):
        scheduler.reserve_model_turn(run_id, job["assignment_id"], job["attempt_id"],
                                     persist_receipt=persist)
    assert claims == []
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?",
                          (run_id,)).fetchone()[0] == 0
        assert _count_if_table_exists(db, "study_token_launches") == 0
        assert _count_if_table_exists(db, "study_token_attempts") == 0


@pytest.mark.parametrize("defect", ["arm_event", "run_budget", "missing_manifest", "job_runtime"])
def test_changed_heldout_binding_fails_before_claim_or_runner(tmp_path, defect):
    database = tmp_path / "state.sqlite"
    protocol = _protocol(database, manifest=None if defect == "missing_manifest" else "d" * 64,
                         run_tokens=4097 if defect == "run_budget" else 10_000)
    database, scheduler, _protocol_obj, run_id, job = _running_slot(tmp_path, protocol=protocol)
    if defect in {"arm_event", "run_budget"}:
        with sqlite3.connect(database) as db:
            payload = json.loads(db.execute(
                "SELECT payload FROM heldout_arm_bindings WHERE run_id=?", (run_id,),
            ).fetchone()[0])
            if defect == "arm_event":
                payload["arm"] = "without_planner"
            else:
                payload["budget"]["tokens"] = 4097
            db.execute("UPDATE heldout_arm_bindings SET payload=? WHERE run_id=?",
                       (json.dumps(payload), run_id))
    if defect == "job_runtime":
        with sqlite3.connect(database) as db:
            db.execute("UPDATE agent_jobs SET host='other-runtime' WHERE assignment_id=?",
                       (job["assignment_id"],))
    admission = StudyTokenAdmission(database)
    runner = AdmittedFakeRunner(database)
    with pytest.raises(ValueError):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner,
                       study_token_admission=admission)
    assert runner.calls == []
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0
    with sqlite3.connect(database) as db:
        assert _count_if_table_exists(db, "study_token_launches") == 0

