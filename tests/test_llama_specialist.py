from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis.core.llama_server_backend import LlamaBackendStopped
from metis.core.llama_specialist import LlamaSpecialist


def _runner(tmp_path: Path) -> LlamaSpecialist:
    return LlamaSpecialist(model_id="pinned-shisa", binary=tmp_path / "server",
                           binary_sha256="a" * 64, model_path=tmp_path / "model.gguf",
                           model_sha256="b" * 64, database=tmp_path / "state.db",
                           budget_key="shared-run", token_limit=1000, max_output_tokens=16)


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


def test_real_heldout_binding_rejects_adapter_before_reservation(tmp_path, monkeypatch):
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
    monkeypatch.setattr("metis.evaluation.heldout_arm.binding",
                        lambda _db, _run: {"model_pin": "pinned-shisa", "prompt_text": "pinned"})
    with pytest.raises(ValueError, match="token cap is not enforceable"):
        run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"],
                       _runner(tmp_path))
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
