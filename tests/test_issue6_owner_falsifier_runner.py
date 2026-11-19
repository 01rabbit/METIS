from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_issue6_owner_falsifier as study
from metis.evaluation.issue6_owner_falsifier import make_task


class FakeSession:
    def intake(self, **kwargs: Any) -> dict[str, str]:
        return {"run_id": "run-test"}

    def context(self, run_id: str) -> dict[str, Any]:
        return {"challenge": {"artifacts": ["artifact-ref"]}}


class FakeScheduler:
    ledger = object()

    def configure(self, **kwargs: Any) -> None:
        pass

    def model_turn_budget(self, run_id: str) -> dict[str, int]:
        return {"reserved": 4}

    def candidates(self, run_id: str, *, purge: str | None = None) -> list[Any]:
        assert purge == "all"
        return []

    def jobs(self, run_id: str) -> list[dict[str, str]]:
        return [{"state": "completed"}]


@pytest.mark.parametrize(
    ("checker", "repair", "owner_state", "expected_verified", "expected_stages"),
    [
        (None, None, "completed", False, 2),
        ("invalid", None, "completed", False, 2),
        ("valid", "repaired", "completed", True, 3),
        (None, None, "failed", False, 1),
        ("budget", None, "completed", False, 1),
    ],
)
def test_run_arm_requires_completed_validated_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker: str | None,
    repair: str | None, owner_state: str, expected_verified: bool, expected_stages: int,
) -> None:
    task, answer = make_task(2026111908)
    wrong = list(answer)
    wrong[0], wrong[1] = wrong[1], wrong[0]
    responses: list[tuple[dict[str, Any], str | None, bool]] = [
        ({"job_state": owner_state, "codex_turns": [{"usage": None}]}, json.dumps(wrong), True)
    ]
    if owner_state == "completed" and checker != "budget":
        witness = None
        if checker == "valid":
            witness = json.dumps({"kind": "precedence", "before": answer[0], "after": answer[1]})
        elif checker == "invalid":
            witness = json.dumps({"kind": "missing", "symbol": answer[0]})
        responses.append(({"job_state": "completed", "codex_turns": [{"usage": {}}]}, witness, True))
    if repair == "repaired":
        responses.append(({"job_state": "completed", "codex_turns": [{"usage": {}}]}, json.dumps(answer), True))
    notes: list[str] = []

    def wave(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if checker == "budget" and len(notes) == 1:
            raise ValueError("no calls left")
        return {"wave_id": f"wave-{len(notes)}"}

    def run_wave(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], str | None, bool]:
        notes.append(args[-1])
        return responses.pop(0)

    monkeypatch.setattr(study, "_wave", wave)
    monkeypatch.setattr(study, "_run_wave", run_wave)
    row = study.run_arm(FakeSession(), FakeScheduler(), SimpleNamespace(), tmp_path,
                        "task-02", task, answer, "owner_falsifier")  # type: ignore[arg-type]
    assert row["workflow_verified"] is expected_verified
    assert row["oracle_verified"] is expected_verified
    assert len(row["stage_states"]) == expected_stages
    assert row["usage_reported_turns"] == expected_stages - 1
    assert row["usage_total_turns"] == expected_stages
    assert not responses
    if checker == "valid":
        assert row["witness_valid"] and row["repair_attempted"]
        assert json.dumps(wrong) in notes[1]
        assert json.dumps(answer) not in notes[1]
    else:
        assert not row["repair_attempted"]


def test_checkpoint_refuses_interrupted_arm_and_changed_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    task_order = study._trial_order()
    first_case, first_arm = task_order[0]
    row = {"case": first_case, "arm": first_arm, "run_id": "run-test",
           "calls_reserved": 4, "calls_observed": 3, "job_states": ["completed"]}
    scheduler = SimpleNamespace(
        database=tmp_path / "audit.sqlite",
        model_turn_budget=lambda run_id: {"reserved": 4},
        jobs=lambda run_id: [{"state": "completed"}],
    )
    with sqlite3.connect(scheduler.database) as db:
        db.execute("CREATE TABLE agent_run_turn_budgets(run_id TEXT)")
        db.execute("INSERT INTO agent_run_turn_budgets VALUES ('run-test')")
    monkeypatch.setattr(study, "_audit_turn_counts", lambda database, run_id: (4, 3))
    manifest = {"study": study.STUDY, "seed": study.SEED, "active": None, "records": [row]}
    old_output = study.OUTPUT
    study.OUTPUT = tmp_path / "output.json"
    try:
        assert study._validate_checkpoint(manifest, scheduler) == [row]  # type: ignore[arg-type]
        manifest["active"] = {"case": "task-01", "arm": "single"}
        with pytest.raises(ValueError, match="interrupted arm"):
            study._validate_checkpoint(manifest, scheduler)  # type: ignore[arg-type]
        manifest["active"] = None
        scheduler.model_turn_budget = lambda run_id: {"reserved": 5}
        with pytest.raises(ValueError, match="call accounting"):
            study._validate_checkpoint(manifest, scheduler)  # type: ignore[arg-type]
        scheduler.model_turn_budget = lambda run_id: {"reserved": 4}
        monkeypatch.setattr(study, "_audit_turn_counts", lambda database, run_id: (4, 2))
        with pytest.raises(ValueError, match="observed call log"):
            study._validate_checkpoint(manifest, scheduler)  # type: ignore[arg-type]
        study.OUTPUT.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="retained output"):
            study._validate_checkpoint(manifest, scheduler)  # type: ignore[arg-type]
    finally:
        study.OUTPUT = old_output
