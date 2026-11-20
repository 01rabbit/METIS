from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from metis.core.codex_specialist import _decision
from metis.core.llama_server_backend import (
    LlamaBackendError,
    LlamaBackendStopped,
    LlamaServerBackend,
)
from metis.core.llama_specialist import LlamaSpecialist
from metis.core.study_token_admission import (
    SlotTokenPin,
    StudyTokenPin,
    TokenAdmissionReceipt,
    TokenAttempt,
    TokenLaunchClaim,
)
from metis.core.token_reservation import FULL_CONTEXT_RESERVATION_TOKENS


def _runner(tmp_path: Path) -> LlamaSpecialist:
    return LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
                           binary_sha256="a" * 64, model_path=tmp_path / "model.gguf",
                           model_sha256="b" * 64, database=tmp_path / "state.db",
                           budget_key="shared-run", token_limit=1000, max_output_tokens=16)


def _pin(runner: LlamaSpecialist) -> dict:
    config = runner.backend_config
    return {"binary_sha256": config["binary_sha256"],
            "model_sha256": config["model_sha256"],
            "database_path": str(config["database"].resolve()),
            "budget_key": config["budget_key"], "token_limit": config["token_limit"],
            "max_output_tokens": config["max_output_tokens"],
            "context_reservation": config["context_reservation"],
            "native_manifest_sha256": runner.native_manifest_sha256}


@pytest.mark.parametrize("changed", ["binary_sha256", "model_sha256", "database_path",
                                     "budget_key", "token_limit", "max_output_tokens",
                                     "context_reservation", "native_manifest_sha256"])
def test_heldout_llama_pin_rejects_each_mismatch(tmp_path, changed):
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
                             binary_sha256="a" * 64, model_path=tmp_path / "model.gguf",
                             model_sha256="b" * 64, database=tmp_path / "state.db",
                             budget_key="study-budget", token_limit=10000,
                             max_output_tokens=16, context_reservation=True)
    pin = _pin(runner)
    runner.assert_heldout_binding({"llama_backend": pin}, tmp_path / "state.db", "pinned-shisa")
    wrong = dict(pin)
    wrong[changed] = not pin[changed] if changed == "context_reservation" else "wrong"
    with pytest.raises(ValueError, match="preregistered pin"):
        runner.assert_heldout_binding({"llama_backend": wrong}, tmp_path / "state.db", "pinned-shisa")
    with pytest.raises(ValueError, match="preregistered pin"):
        runner.assert_heldout_binding({"llama_backend": pin}, tmp_path / "other.db", "pinned-shisa")


def test_adapter_records_usage_isolation_and_tool_free_prompt(tmp_path, monkeypatch):
    seen = []
    class FakeBackend:
        def __init__(self, **config):
            seen.append(config)
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def complete(self, prompt, **kwargs):
            seen.append((prompt, kwargs))
            return json.dumps({"action": "fail", "intent": None, "report": None,
                               "reason": "No supported hypothesis.", "candidate": None}), 42, 8
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    runner = _runner(tmp_path)
    turn = runner.run("harmless assignment", model="pinned-shisa", timeout=5)
    assert turn.returncode == 0 and turn.usage == {"input_tokens": 42, "output_tokens": 8}
    assert turn.isolation["mode"] == "local_unix_socket" and turn.item_types == ["agent_message"]
    assert '"required":["action","intent","report","reason","candidate"]' in seen[1][0]
    assert seen[0]["budget_key"] == "shared-run" and seen[1][1]["n_predict"] == 16
    assert runner.model_turn_budget_enforced and not runner.hard_token_budget_enforced


def test_model_pin_and_images_rejected_before_backend(tmp_path):
    runner = _runner(tmp_path)
    mismatch = runner.run("prompt", model="other", timeout=5)
    image = runner.run("prompt", model="pinned-shisa", timeout=5, images=[(".png", b"x")])
    assert mismatch.returncode == image.returncode == 1
    assert mismatch.message is image.message is None


def test_cancel_before_and_during_call(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    before = runner.run("prompt", model="pinned-shisa", timeout=5, should_stop=lambda: True)
    assert before.stopped and before.message is None
    class CancelBackend:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def complete(self, _prompt, **kwargs):
            assert kwargs["should_stop"] is not None
            raise LlamaBackendStopped("cancelled")
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", CancelBackend)
    during = runner.run("prompt", model="pinned-shisa", timeout=5, should_stop=lambda: False)
    assert during.stopped and during.message is None


def test_invalid_json_retains_observed_usage(tmp_path, monkeypatch):
    class BadBackend:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def complete(self, _prompt, **_kwargs): return "not json", 10, 4
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", BadBackend)
    turn = _runner(tmp_path).run("prompt", model="pinned-shisa", timeout=5)
    assert turn.returncode == 0 and turn.message == "not json"
    assert turn.usage == {"input_tokens": 10, "output_tokens": 4}


def test_run_assignment_records_local_usage_and_shared_turn_budget(tmp_path, monkeypatch):
    from metis.core.agent_host import BridgeHost
    from metis.core.agent_scheduler import AgentScheduler
    from metis.core.codex_session import CodexSession
    from metis.core.codex_specialist import run_assignment
    from metis.core.ctf_orchestration import AgentLedger

    db = tmp_path / "assignment.sqlite"
    parts = []
    for number in range(2):
        part = tmp_path / f"part{number}.txt"
        part.write_text("sample")
        parts.append(part)
    run_id = CodexSession(db).intake(title="Synthetic", description="Inspect samples.",
                                         paths=parts, categories=["crypto", "forensics"],
                                         max_actions=80)["run_id"]
    wave = AgentLedger(db).create_wave(run_id)
    scheduler = AgentScheduler(db, BridgeHost())
    scheduler.configure(per_run_slots=2, catalog=[{"id": "pinned-shisa", "tier": "standard"}],
                        current_model="pinned-shisa")
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]

    class FakeBackend:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def complete(self, _prompt, **_kwargs):
            return json.dumps({"action": "fail", "intent": None, "report": None,
                               "reason": "No supported hypothesis.", "candidate": None}), 42, 8

    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    runner = _runner(tmp_path)
    outcome = run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner)
    assert outcome["job_state"] == "failed"
    usage = next(row["usage"] for row in scheduler.jobs(run_id)
                 if row["assignment_id"] == job["assignment_id"])
    assert usage["host"] == "llama-server"
    assert usage["input_tokens"] == 42 and usage["output_tokens"] == 8
    assert scheduler.model_turn_budget(run_id)["reserved"] == 1


@pytest.mark.parametrize("pin_state", ["missing", "mismatched", "matched"])
def test_real_heldout_binding_rejects_adapter_before_reservation(tmp_path, monkeypatch, pin_state):
    from metis.core.agent_host import BridgeHost
    from metis.core.agent_scheduler import AgentScheduler
    from metis.core.codex_session import CodexSession
    from metis.core.codex_specialist import run_assignment
    from metis.core.ctf_orchestration import AgentLedger

    db = tmp_path / "heldout.sqlite"
    paths = []
    for number in range(2):
        path = tmp_path / f"item{number}.txt"
        path.write_text("sample")
        paths.append(path)
    run_id = CodexSession(db).intake(title="Synthetic", description="Inspect samples.",
                                         paths=paths, categories=["crypto", "forensics"],
                                         max_actions=80)["run_id"]
    wave = AgentLedger(db).create_wave(run_id)
    scheduler = AgentScheduler(db, BridgeHost())
    scheduler.configure(per_run_slots=2, catalog=[{"id": "pinned-shisa", "tier": "standard"}],
                        current_model="pinned-shisa")
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
                             binary_sha256="a" * 64, model_path=tmp_path / "model.gguf",
                             model_sha256="b" * 64, database=db, budget_key="study-budget",
                             token_limit=10000, max_output_tokens=16,
                             context_reservation=True)
    bound = {"model_pin": "pinned-shisa", "prompt_text": "pinned"}
    if pin_state != "missing":
        bound["llama_backend"] = _pin(runner)
        if pin_state == "mismatched":
            bound["llama_backend"]["budget_key"] = "other-study"
    monkeypatch.setattr("metis.evaluation.heldout_arm.binding", lambda _db, _run: bound)
    expected = {"missing": "backend pin missing", "mismatched": "preregistered pin",
                "matched": "token-admitted runner"}[pin_state]
    with pytest.raises(ValueError, match=expected):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"],
                       runner)
    assert scheduler.model_turn_budget(run_id)["reserved"] == 0


@pytest.mark.parametrize("failure", ["model_mismatch", "oversized_prompt"])
def test_expected_adapter_refusals_fail_assignment_without_driver_exception(tmp_path, monkeypatch, failure):
    from metis.core.agent_host import BridgeHost
    from metis.core.agent_scheduler import AgentScheduler
    from metis.core.codex_session import CodexSession
    from metis.core.codex_specialist import run_assignment
    from metis.core.ctf_orchestration import AgentLedger

    db = tmp_path / "refusal.sqlite"
    files = []
    for number in range(2):
        path = tmp_path / f"part{number}.txt"
        path.write_text("sample")
        files.append(path)
    run_id = CodexSession(db).intake(title="Synthetic", description="Inspect samples.",
                                         paths=files, categories=["crypto", "forensics"],
                                         max_actions=80)["run_id"]
    wave = AgentLedger(db).create_wave(run_id)
    scheduler = AgentScheduler(db, BridgeHost())
    scheduler.configure(per_run_slots=2, catalog=[{"id": "pinned-shisa", "tier": "standard"}],
                        current_model="pinned-shisa")
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]
    runner = _runner(tmp_path)
    if failure == "model_mismatch":
        runner.model_id = "other-pin"
    else:
        class BoundaryBackend:
            def __init__(self, **_): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def complete(self, prompt, **_kwargs):
                assert len(prompt) > 65_536
                raise ValueError("private prompt bytes exceeded input boundary")
        monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", BoundaryBackend)
        monkeypatch.setattr("metis.core.codex_specialist.render_prompt",
                            lambda *_args: "x" * 65_537)
    outcome = run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], runner)
    assert outcome["job_state"] == "failed"
    assert scheduler.model_turn_budget(run_id)["reserved"] == 1
    assert "private prompt bytes" not in json.dumps(outcome)


def _claim(runner: LlamaSpecialist, prompt: str, *, tokens: int | None = None,
           runtime: str | None = None, manifest: str | None = None) -> TokenLaunchClaim:
    config = runner.backend_config
    return TokenLaunchClaim(
        receipt=TokenAdmissionReceipt(
            study=StudyTokenPin(study_id="study", protocol_sha256="c" * 64,
                runtime_sha256=runtime or config["binary_sha256"],
                model_sha256=config["model_sha256"], token_limit=100_000,
                native_manifest_sha256=manifest or "d" * 64),
            slot=SlotTokenPin(run_id="run", task_id="task", repetition=0,
                              arm="single_agent", token_limit=100_000),
            attempt=TokenAttempt(assignment_id="assignment", attempt_id="attempt",
                turn_reservation_id=1, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                tokens=tokens or FULL_CONTEXT_RESERVATION_TOKENS + runner.max_output_tokens)),
        nonce="e" * 32,
    )


def test_run_admitted_validates_claim_and_uses_admitted_backend(tmp_path, monkeypatch):
    prompt = "authorized assignment"
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    native_request = runner.build_native_request(prompt)
    calls = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, claim, *, owner_id):
            assert len(owner_id) == 32
            calls.append(("claim", claim.nonce))
            return "claimed"
        def record_outcome(self, claim, outcome): calls.append(("outcome", outcome.status, outcome.observed_work))
    class FakeBackend:
        def __init__(self, **_config): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def complete_admitted(self, request, **kwargs):
            calls.append(("complete", kwargs["token_cap"], kwargs["n_predict"], request))
            return ('{"action":"fail","intent":null,"report":null,"reason":"none","candidate":null}', 20, 4)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    claim = _claim(runner, native_request)
    turn = runner.run_admitted(native_request, model=runner.model_id, timeout=5,
                               token_claim=claim, admission=Admission())
    assert turn.returncode == 0 and turn.usage == {"input_tokens": 20, "output_tokens": 4}
    assert [call[0] for call in calls] == ["claim", "complete", "outcome"]
    assert calls[-1] == ("outcome", "completed", 24)
    assert hashlib.sha256(calls[1][3].encode()).hexdigest() == claim.receipt.attempt.prompt_sha256
    assert runner.hard_token_budget_enforced is False


@pytest.mark.parametrize("defect", ["prompt", "model", "runtime", "manifest", "images", "cap"])
def test_run_admitted_preflight_rejects_without_consumption_or_backend(tmp_path, monkeypatch, defect):
    prompt = "authorized assignment"
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    native_request = runner.build_native_request(prompt)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome.status)
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend",
                        lambda **_kwargs: pytest.fail("preflight must not start backend"))
    claim = _claim(runner, native_request, runtime="f" * 64 if defect == "runtime" else None,
                   manifest="f" * 64 if defect == "manifest" else None,
                   tokens=FULL_CONTEXT_RESERVATION_TOKENS if defect == "cap" else None)
    turn = runner.run_admitted("changed" if defect == "prompt" else native_request,
        model="wrong" if defect == "model" else runner.model_id, timeout=5,
        token_claim=claim, admission=Admission(),
        images=[(".png", b"x")] if defect == "images" else None)
    assert turn.returncode == 1 and turn.message is None
    assert outcomes == ["receipt_invalid"]


def test_untrusted_deep_json_does_not_overwrite_completed_outcome(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    content = '{"action":"report","report":{"body":' + "[" * 20_000 + "0" + "]" * 20_000 + "}}"
    with pytest.raises(RecursionError):
        _decision(content)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class FakeBackend:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, _prompt, **_kwargs): return content, 12, 3
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", FakeBackend)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=5,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 0 and turn.message == content
    assert outcomes[0].status == "completed" and outcomes[0].observed_work == 15


def test_server_startup_timeout_is_launch_failure_not_model_timeout(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class StartupFailure:
        def __init__(self, **_kwargs): pass
        def __enter__(self): raise LlamaBackendError("server startup timed out")
        def __exit__(self, *_args): pass
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", StartupFailure)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=5,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 1 and not turn.timed_out
    assert outcomes[0].status == "launch_failed"
    assert outcomes[0].exit_status is None and outcomes[0].observed_work is None


def test_admitted_startup_and_completion_share_assignment_deadline(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class SlowStartup:
        def __init__(self, **config): self.config = config
        def __enter__(self):
            time.sleep(.02)
            return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, _prompt, **kwargs):
            assert kwargs["timeout_seconds"] < 1
            assert kwargs["deadline_monotonic"] == self.config["deadline_monotonic"]
            return '{"action":"fail","intent":null,"report":null,"reason":"none","candidate":null}', 12, 3
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", SlowStartup)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=1,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 0 and turn.usage == {"input_tokens": 12, "output_tokens": 3}
    assert outcomes[0].status == "completed"


def test_admitted_startup_past_assignment_deadline_skips_completion(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class SlowStartup:
        def __init__(self, **_config): pass
        def __enter__(self):
            time.sleep(.02)
            return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, *_args, **_kwargs):
            pytest.fail("completion must not begin after the assignment deadline")
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", SlowStartup)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=.01,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 1 and turn.timed_out
    assert outcomes[0].status == "timeout"


def test_admitted_startup_cancellation_records_cancelled_outcome(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class CancelledStartup:
        def __init__(self, **_config): pass
        def __enter__(self): raise LlamaBackendStopped("server startup cancelled")
        def __exit__(self, *_args): pass
        def complete_admitted(self, *_args, **_kwargs):
            pytest.fail("completion must not run after startup cancellation")
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", CancelledStartup)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=1,
        token_claim=_claim(runner, prompt), admission=Admission(), should_stop=lambda: True)
    assert turn.returncode == 1 and turn.stopped and not turn.timed_out
    assert [outcome.status for outcome in outcomes] == ["cancelled"]


def test_integrity_failure_after_deadline_is_not_relabelled_as_timeout(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class ChangedArtifact:
        def __init__(self, **_config): pass
        def __enter__(self):
            time.sleep(.02)
            raise LlamaBackendError("pinned artifact changed")
        def __exit__(self, *_args): pass
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", ChangedArtifact)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=.01,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 1 and not turn.timed_out
    assert [outcome.status for outcome in outcomes] == ["launch_failed"]


def test_non_admitted_run_bounds_startup_and_passes_cancellation(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    stop = lambda: False
    class CancelStartup:
        def __init__(self, **kwargs):
            assert isinstance(kwargs["deadline_monotonic"], float)
            assert kwargs["should_stop"] is stop
        def __enter__(self): raise LlamaBackendStopped("cancelled during startup")
        def __exit__(self, *_args): pass
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", CancelStartup)
    turn = runner.run("prompt", model=runner.model_id, timeout=5, should_stop=stop)
    assert turn.returncode == 1 and turn.stopped


def test_non_admitted_startup_time_counts_against_call_deadline(tmp_path, monkeypatch):
    runner = _runner(tmp_path)
    class SlowStartup:
        def __init__(self, **kwargs):
            assert isinstance(kwargs["deadline_monotonic"], float)
        def __enter__(self):
            time.sleep(.02)
            return self
        def __exit__(self, *_args): pass
        def complete(self, *_args, **_kwargs): pytest.fail("completion must not start after deadline")
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", SlowStartup)
    turn = runner.run("prompt", model=runner.model_id, timeout=.01)
    assert turn.returncode == 1 and turn.timed_out


@pytest.mark.parametrize(("reason", "status"), [
    ("server startup timed out", "launch_failed"),
    ("server exited during startup", "launch_failed"),
])
def test_server_startup_outcomes_distinguish_timeout_and_exit(tmp_path, monkeypatch, reason, status):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class StartupFailure:
        def __init__(self, **_kwargs): pass
        def __enter__(self): raise LlamaBackendError(reason)
        def __exit__(self, *_args): pass
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", StartupFailure)
    standalone = runner.run("assignment", model=runner.model_id, timeout=5)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=5,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert standalone.returncode == turn.returncode == 1
    assert standalone.timed_out == turn.timed_out == (status == "timeout")
    assert outcomes[0].status == status
    assert outcomes[0].exit_status is None and outcomes[0].observed_work is None


def test_admitted_startup_receives_call_deadline_and_cancellation(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    stop = lambda: False
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class CancelDuringStartup:
        def __init__(self, **kwargs):
            assert isinstance(kwargs["deadline_monotonic"], float)
            assert kwargs["should_stop"] is stop
        def __enter__(self): raise LlamaBackendStopped("model call cancelled during server startup")
        def __exit__(self, *_args): pass
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", CancelDuringStartup)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=5,
        token_claim=_claim(runner, prompt), admission=Admission(), should_stop=stop)
    assert turn.returncode == 1 and turn.stopped
    assert outcomes[0].status == "cancelled"


def test_admitted_startup_time_counts_against_total_call_deadline(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)
    class SlowStartup:
        def __init__(self, **_kwargs): pass
        def __enter__(self):
            __import__("time").sleep(.02)
            return self
        def __exit__(self, *_args): pass
        def complete_admitted(self, *_args, **_kwargs): pytest.fail("completion must not start after deadline")
    monkeypatch.setattr("metis.core.llama_specialist.LlamaServerBackend", SlowStartup)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=.01,
        token_claim=_claim(runner, prompt), admission=Admission())
    assert turn.returncode == 1 and turn.timed_out
    assert outcomes[0].status == "timeout"


def test_admitted_cancellation_after_completion_response_preserves_usage(tmp_path, monkeypatch):
    prompt = LlamaSpecialist.build_native_request("assignment")
    runner = LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
        binary_sha256="a" * 64, model_path=tmp_path / "model.gguf", model_sha256="b" * 64,
        database=tmp_path / "state.db", budget_key="study", token_limit=100_000,
        max_output_tokens=16, context_reservation=True, native_manifest_sha256="d" * 64)
    outcomes = []
    completion_started = threading.Event()
    waiting_for_response = threading.Event()
    cancelled = threading.Event()

    class Admission:
        database = tmp_path / "state.db"
        def is_consumed_scheduler_launch_claim(self, _claim): return True
        def claim_scheduler_native_launch(self, _claim, *, owner_id): return "claimed"
        def record_outcome(self, _claim, outcome): outcomes.append(outcome)

    def stop() -> bool:
        already_cancelled = cancelled.is_set()
        if completion_started.is_set():
            waiting_for_response.set()
        return already_cancelled

    def request(backend, route, payload, *, timeout):
        if route == "/tokenize":
            return {"tokens": [1]}
        assert route == "/completion"
        completion_started.set()
        if not waiting_for_response.wait(2):
            raise LlamaBackendError("completion fixture did not reach the cancellation check")
        cancelled.set()
        return {"content": "late response", "tokens_evaluated": 1, "tokens_predicted": 1,
                "generation_settings": {"n_predict": payload["n_predict"]},
                "model": str(backend.model)}

    monkeypatch.setattr(LlamaServerBackend, "__enter__", lambda backend: backend)
    monkeypatch.setattr(LlamaServerBackend, "_request", request)
    turn = runner.run_admitted(prompt, model=runner.model_id, timeout=5,
        token_claim=_claim(runner, prompt), admission=Admission(), should_stop=stop)

    assert cancelled.is_set()
    assert turn.returncode == 0 and not turn.stopped
    assert turn.usage == {"input_tokens": 1, "output_tokens": 1}
    assert [outcome.status for outcome in outcomes] == ["completed"]
    assert outcomes[0].observed_work == 2
