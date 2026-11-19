"""Pre-dispatch study gate; no model, artifact, or CTF calls."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from metis.evaluation.heldout_ollama_study import (
    OUTPUT_CAP_PER_TURN,
    registered_runner,
    run_registered_slot,
)
from metis.evaluation.heldout_protocol import Protocol, digest


def protocol() -> Protocol:
    prompt_hash = hashlib.sha256(b"fixed prompt").hexdigest()
    arms = ["full", "without_memory", "without_planner", "single_agent"]
    budget = {"model_calls": 3, "tokens": 10_000, "actions": 20,
              "seconds": 300.0, "cost_usd": None}
    configs = {
        "full": (True, True, 2),
        "without_memory": (False, True, 2),
        "without_planner": (True, False, 2),
        "single_agent": (True, True, 1),
    }
    return Protocol.model_validate({
        "schema_version": 1, "study_id": "new-local-study", "measurement": "real_model",
        "model_pin": "gemma4:12b", "runtime_pin": "bridge", "seed": 1,
        "repetitions": 2, "arms": arms, "baseline": "full",
        "budgets": {arm: budget for arm in arms},
        "tasks": [{"task_id": f"task{i}", "source_id": f"source{i}",
                   "distribution_sha256": f"{i+1:064x}", "category": "rev",
                   "difficulty": "easy", "split": "held_out", "exposure": "unseen",
                   "solvability_control_verified": True} for i in range(2)],
        "arm_config": {arm: {"memory_enabled": memory, "planner_enabled": planner,
                              "max_specialists": specialists, "prompt_sha256": prompt_hash}
                       for arm, (memory, planner, specialists) in configs.items()},
        "memory_card_digests": ["a" * 64],
    })


RUNTIME_PROFILE = {"engine": "test-ollama", "model": "gemma4:12b"}
RUNTIME_SHA256 = hashlib.sha256(json.dumps(RUNTIME_PROFILE, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()


def bound(database: Path, study: Protocol, arm: str, *, token_override: int | None = None) -> str:
    run_id = "a" * 32
    payload = {"protocol_sha256": digest(study), "task_id": "task0", "repetition": 0,
               "arm": arm, "arm_config": study.arm_config[arm].model_dump(mode="json"),
               "model_pin": study.model_pin, "runtime_pin": study.runtime_pin,
               "budget": study.budgets[arm].model_dump(mode="json"), "prompt_text": "fixed prompt"}
    if token_override is not None:
        payload["budget"]["tokens"] = token_override
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE heldout_arm_bindings (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO heldout_arm_bindings VALUES (?,?)", (run_id, json.dumps(payload)))
    return run_id


@pytest.mark.parametrize("arm", ["full", "without_memory", "without_planner", "single_agent"])
def test_all_arms_use_same_cap_before_autopilot(tmp_path: Path, monkeypatch, arm: str) -> None:
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.OllamaSpecialist.hard_token_budget_enforced", True)
    study = protocol()
    database = tmp_path / "state.sqlite"
    run_id = bound(database, study, arm)
    calls = []
    engine = SimpleNamespace(model="gemma4:12b", verify_model=lambda: calls.append("verified"),
                             runtime_profile=lambda cap: RUNTIME_PROFILE)
    def fake_autopilot(scheduler, selected_run, runner, *, max_waves):  # type: ignore[no-untyped-def]
        calls.append((selected_run, runner.budget.limit, runner.output_cap, max_waves))
        return {"stop": "test-only"}
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.autopilot", fake_autopilot)
    result = run_registered_slot(SimpleNamespace(database=database), run_id, study,
                                 expected_sha256=digest(study),
                                 expected_runtime_sha256=RUNTIME_SHA256, engine=engine)
    assert result["stop"] == "test-only"
    assert calls == ["verified", (run_id, 10_000, OUTPUT_CAP_PER_TURN, 1)]


@pytest.mark.parametrize("change", ["digest", "budget", "model", "old"])
def test_mismatch_rejected_before_model_dispatch(tmp_path: Path, monkeypatch, change: str) -> None:
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.OllamaSpecialist.hard_token_budget_enforced", True)
    study = protocol()
    database = tmp_path / "state.sqlite"
    run_id = bound(database, study, "full", token_override=9999 if change == "budget" else None)
    calls = []
    engine = SimpleNamespace(model="wrong" if change == "model" else "gemma4:12b",
                             verify_model=lambda: calls.append("verified"),
                             runtime_profile=lambda cap: RUNTIME_PROFILE)
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.autopilot",
                        lambda *args, **kwargs: calls.append("autopilot"))
    if change == "old":
        monkeypatch.setattr("metis.evaluation.heldout_ollama_study.EXPLORATORY_PROTOCOL_SHA256", digest(study))
    with pytest.raises(ValueError):
        run_registered_slot(SimpleNamespace(database=database), run_id, study,
                            expected_sha256="0" * 64 if change == "digest" else digest(study),
                            expected_runtime_sha256=RUNTIME_SHA256,
                            engine=engine)
    assert calls == []


@pytest.mark.parametrize("arm", ["full", "without_memory", "without_planner", "single_agent"])
def test_mutable_tag_runtime_refused_for_every_arm(tmp_path: Path, monkeypatch, arm: str) -> None:
    study = protocol()
    database = tmp_path / "state.sqlite"
    run_id = bound(database, study, arm)
    calls = []
    engine = SimpleNamespace(model="gemma4:12b", verify_model=lambda: calls.append("verified"))
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.autopilot",
                        lambda *args, **kwargs: calls.append("autopilot"))
    with pytest.raises(ValueError, match="cannot enforce a hard held-out token cap"):
        run_registered_slot(SimpleNamespace(database=database), run_id, study,
                            expected_sha256=digest(study),
                            expected_runtime_sha256=RUNTIME_SHA256, engine=engine)
    assert calls == []


def test_runtime_profile_cannot_change_between_slots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("metis.evaluation.heldout_ollama_study.OllamaSpecialist.hard_token_budget_enforced", True)
    study = protocol()
    database = tmp_path / "state.sqlite"
    run_id = bound(database, study, "full")
    scheduler = SimpleNamespace(database=database)
    first = SimpleNamespace(model="gemma4:12b", verify_model=lambda: None,
                            runtime_profile=lambda cap: RUNTIME_PROFILE)
    registered_runner(scheduler, run_id, study, expected_sha256=digest(study),
                      expected_runtime_sha256=RUNTIME_SHA256, engine=first)
    changed = {**RUNTIME_PROFILE, "ollama_version": "changed"}
    changed_hash = hashlib.sha256(json.dumps(changed, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    second = SimpleNamespace(model="gemma4:12b", verify_model=lambda: None,
                             runtime_profile=lambda cap: changed)
    with pytest.raises(ValueError, match="changed between study arms"):
        registered_runner(scheduler, run_id, study, expected_sha256=digest(study),
                          expected_runtime_sha256=changed_hash, engine=second)
