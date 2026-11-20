"""P7 analysis fixtures; these verdicts are invented, never measured solves."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from metis.core.contracts import RunEvent, RunStatus
from metis.core.store import RunStore
from metis.evaluation.heldout_analysis import Study, _analyze_with_verified_controls, analyze, main


def fixture_metrics() -> dict:
    arms = ["full", "without_memory", "without_planner", "single_agent"]
    tasks = [{"task_id": f"synthetic-{index}", "category": category,
              "difficulty": difficulty, "split": "held_out", "exposure": "unseen",
              "solvability_control_verified": True}
             for index, (category, difficulty) in enumerate(
                 [("crypto", "easy"), ("misc", "medium"), ("rev", "hard")])]
    trials = []
    for index, task in enumerate(tasks):
        for repetition in range(2):
            for arm in arms:
                verified = arm == "full" or index == 0
                trials.append({
                    "task_id": task["task_id"], "repetition": repetition, "arm": arm,
                    "run_id": f"{len(trials):032x}", "evidence_sequence": 1,
                    "oracle": "protected_fixture", "oracle_verified": verified,
                    "workflow_complete": True, "failure": "none" if verified else "incorrect",
                    "seconds": 1.0 + repetition, "model_calls": 2, "actions": 1,
                    "tokens": 100, "cost_usd": None,
                })
    return {
        "schema_version": 1, "study_id": "issue8-analysis-synthetic-fixture",
        "measurement": "synthetic_fixture", "model_pin": "no-model-fixture",
        "runtime_pin": "pytest-no-runtime", "seed": 20261118, "repetitions": 2,
        "arms": arms, "baseline": "single_agent",
        "budgets": {arm: {"model_calls": 8, "tokens": 1000, "actions": 4,
                          "seconds": 600.0, "cost_usd": None} for arm in arms},
        "tasks": tasks, "trials": trials,
    }


def _ledger_backed_study(tmp_path: Path, *, verification: str = "official_ctfd",
                         oracle: str = "official") -> tuple[Study, Path]:
    data = fixture_metrics()
    data["arms"] = ["full", "single_agent"]
    data["baseline"] = "single_agent"
    data["budgets"] = {arm: data["budgets"][arm] for arm in data["arms"]}
    data["repetitions"] = 2
    data["tasks"] = data["tasks"][:2]
    data["trials"] = [trial for trial in data["trials"]
                      if trial["task_id"] in {task["task_id"] for task in data["tasks"]}
                      and trial["arm"] in data["arms"]]
    database = tmp_path / "ledger.sqlite"
    store = RunStore(database)
    for index, trial in enumerate(data["trials"]):
        run_id = f"{index + 1:032x}"
        trial["run_id"] = run_id
        trial["oracle"] = oracle
        trial["evidence_sequence"] = 7
        for sequence, status in enumerate((RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED,
                                           RunStatus.PLANNING, RunStatus.EXECUTING, RunStatus.OBSERVING,
                                           RunStatus.VERIFYING, RunStatus.SOLVED)):
            detail = {"verification": verification} if sequence == 7 else {}
            store.append(RunEvent(run_id=run_id, sequence=sequence, status=status, detail=detail))
    return Study.model_validate(data), database


def test_paired_cluster_analysis_retains_repetitions_and_unknown_cost():
    summary = analyze(Study.model_validate(fixture_metrics()), samples=1000)
    assert summary["measurement"] == "synthetic_fixture"
    assert summary["distinct_task_clusters"] == 3
    assert summary["arms"]["full"]["scored_solves"] == 6
    assert summary["arms"]["single_agent"]["scored_solves"] == 2
    assert summary["acceptance_control_attestation_verified"] is False
    assert summary["unauthenticated_control_excluded_trials"] == 24
    assert summary["arms"]["full"]["acceptance_eligible_solves"] is None
    comparison = summary["comparisons"]["full_minus_single_agent"]
    assert comparison["paired_solve_rate_difference"] == pytest.approx(2 / 3)
    assert comparison["paired_cluster_bootstrap_95_interval"] == [0.0, 1.0]
    assert summary["arms"]["full"]["total_cost_usd"] is None
    assert summary["arms"]["full"]["unknown_cost_trials"] == 6
    assert summary["arms"]["single_agent"]["declared_failures"] == {"incorrect": 4}


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "reuse_run", "unequal_budget"])
def test_design_rejects_nonindependent_or_unmatched_trials(mutation):
    data = fixture_metrics()
    if mutation == "duplicate":
        data["trials"].append(data["trials"][0])
    elif mutation == "missing":
        data["trials"].pop()
    elif mutation == "reuse_run":
        data["trials"][1]["run_id"] = data["trials"][0]["run_id"]
    else:
        data["budgets"]["full"]["tokens"] += 1
    with pytest.raises(ValidationError):
        Study.model_validate(data)


@pytest.mark.parametrize("exposure", ["prior_solved", "prior_answer", "unknown"])
def test_contaminated_tasks_remain_in_denominator_and_cannot_score(exposure):
    data = fixture_metrics()
    data["tasks"][0]["exposure"] = exposure
    summary = analyze(Study.model_validate(data), samples=100)
    assert summary["arms"]["full"]["trials"] == 6
    assert summary["arms"]["full"]["scored_solves"] == 4
    assert summary["contamination_excluded_trials"] == {f"held_out:{exposure}": 8}


def test_archive_local_and_incomplete_oracle_hits_do_not_score():
    data = fixture_metrics()
    data["trials"][0]["oracle"] = "archive_local"
    data["trials"][4]["workflow_complete"] = False
    data["trials"][4]["failure"] = "incomplete"
    summary = analyze(Study.model_validate(data), samples=100)
    assert summary["arms"]["full"]["scored_solves"] == 4
    assert summary["arms"]["full"]["untrusted_oracle_trials"] == 1


def test_missing_solvability_control_disqualifies_without_removing_trials():
    data = fixture_metrics()
    data["tasks"][0]["solvability_control_verified"] = False
    summary = analyze(Study.model_validate(data), samples=100)
    assert summary["arms"]["full"]["trials"] == 6
    assert summary["arms"]["full"]["scored_solves"] == 4
    assert summary["solvability_controls_missing"] == 1
    assert summary["unresolved_solvability_control_excluded_trials"] == 8


def test_unknown_usage_and_overruns_are_not_hidden():
    data = fixture_metrics()
    data["trials"][0]["tokens"] = None
    data["trials"][4]["tokens"] = 1001
    summary = analyze(Study.model_validate(data), samples=100)
    assert summary["arms"]["full"]["mean_tokens"] is None
    assert summary["arms"]["full"]["budget_overrun_trials"] == 1
    assert summary["arms"]["full"]["scored_solves"] == 5


@pytest.mark.parametrize("missing", ["tokens", "cost_usd", "cost_cap", None])
def test_acceptance_scoring_requires_complete_resources_and_a_cost_cap(missing):
    data = fixture_metrics()
    for budget in data["budgets"].values():
        budget["cost_usd"] = 1.0
    for trial in data["trials"]:
        trial["cost_usd"] = 0.1
    if missing == "cost_cap":
        for budget in data["budgets"].values():
            budget["cost_usd"] = None
    elif missing is not None:
        data["trials"][0][missing] = None
    result = _analyze_with_verified_controls(Study.model_validate(data), samples=100)
    arm = result["arms"]["full"]
    assert arm["trials"] == 6
    assert arm["scored_solves"] == 6  # A diagnostic correctness count, not acceptance.
    assert arm["acceptance_eligible_solves"] == (0 if missing == "cost_cap" else
                                                 6 if missing is None else 5)
    assert arm["acceptance_ineligible_resource_trials"] == (6 if missing == "cost_cap" else
                                                           0 if missing is None else 1)


@pytest.mark.parametrize("field,value", [("candidate", "SECRET_SENTINEL"),
                                         ("seconds", float("nan")),
                                         ("tokens", True)])
def test_extra_private_fields_nonfinite_and_coercions_rejected(field, value):
    data = fixture_metrics()
    data["trials"][0][field] = value
    with pytest.raises(ValidationError):
        Study.model_validate(data)


def test_cli_rejects_private_data_without_echoing_it(tmp_path, monkeypatch, capsys):
    data = fixture_metrics()
    data["trials"][0]["candidate"] = "SECRET_SENTINEL"
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["analysis", str(metrics)])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SECRET_SENTINEL" not in captured.err


def test_cli_round_trip_answer_free_metrics(tmp_path, monkeypatch, capsys):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps(fixture_metrics()))
    monkeypatch.setattr(sys, "argv", ["analysis", str(metrics)])
    assert main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["arms"]["full"]["scored_solves"] == 6
    assert "run_id" not in json.dumps(summary)


def test_retained_synthetic_input_reproduces_published_fixture_summary():
    fixtures = Path(__file__).resolve().parents[1] / "docs" / "reports" / "fixtures"
    payload = json.loads((fixtures / "issue8-analysis-synthetic-input.json").read_text())
    assert payload == fixture_metrics()
    summary = json.loads((fixtures / "issue8-analysis-synthetic-summary.json").read_text())
    assert analyze(Study.model_validate(payload)) == summary


def test_ledger_reconciliation_checks_every_reference_and_official_provenance(tmp_path, monkeypatch, capsys):
    study, database = _ledger_backed_study(tmp_path)
    before = database.read_bytes()
    metrics = tmp_path / "metrics.json"
    metrics.write_text(study.model_dump_json())
    monkeypatch.setattr(sys, "argv", ["analysis", str(metrics), "--database", str(database)])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ledger_reconciliation"] == {
        "trials_reconciled": 8, "official_verified_trials": 6, "protected_fixture_verified_trials": 0,
    }
    assert "run_id" not in json.dumps(output)
    assert database.read_bytes() == before


def test_ledger_reconciliation_keeps_protected_fixture_provenance_distinct(tmp_path):
    study, database = _ledger_backed_study(tmp_path, verification="local_fixture_oracle",
                                           oracle="protected_fixture")
    from metis.evaluation.heldout_analysis import reconcile_evidence

    assert reconcile_evidence(study, database) == {
        "trials_reconciled": 8, "official_verified_trials": 0, "protected_fixture_verified_trials": 6,
    }


def test_ledger_reconciliation_does_not_create_missing_database(tmp_path, monkeypatch, capsys):
    study, _database = _ledger_backed_study(tmp_path)
    metrics = tmp_path / "metrics.json"
    metrics.write_text(study.model_dump_json())
    missing = tmp_path / "absent.sqlite"
    monkeypatch.setattr(sys, "argv", ["analysis", str(metrics), "--database", str(missing)])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "benchmark metrics rejected" in captured.err
    assert not missing.exists()


@pytest.mark.parametrize("mutation", ["wrong_sequence", "browser_attestation", "local_commitment", "missing_run"])
def test_ledger_reconciliation_rejects_unsubstantiated_official_trials(tmp_path, monkeypatch, capsys, mutation):
    study, database = _ledger_backed_study(
        tmp_path, verification=("official_browser_observed" if mutation == "browser_attestation" else
                                "local_sha256_commitment" if mutation == "local_commitment" else "official_ctfd"))
    trial = study.trials[0]
    if mutation == "wrong_sequence":
        trial = trial.model_copy(update={"evidence_sequence": 6})
        study = study.model_copy(update={"trials": [trial, *study.trials[1:]]})
    elif mutation == "missing_run":
        trial = trial.model_copy(update={"run_id": "f" * 32})
        study = study.model_copy(update={"trials": [trial, *study.trials[1:]]})
    metrics = tmp_path / "metrics.json"
    metrics.write_text(study.model_dump_json())
    monkeypatch.setattr(sys, "argv", ["analysis", str(metrics), "--database", str(database)])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "benchmark metrics rejected" in captured.err
    assert "official_browser_observed" not in captured.err
