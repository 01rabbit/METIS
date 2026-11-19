"""Controller-derived, answer-free held-out export checks."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from metis.core.store import RunStore
from metis.evaluation.heldout_analysis import reconcile_evidence
from metis.evaluation.heldout_export import ExportManifest, export


def fixture(tmp_path: Path) -> tuple[Path, ExportManifest]:
    dbpath = tmp_path / "state.sqlite"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE events (run_id TEXT, sequence INTEGER, payload TEXT, "
                   "timestamp TEXT, previous_hash TEXT, digest TEXT)")
        db.execute("CREATE TABLE codex_sessions (run_id TEXT, evaluation_split TEXT)")
        db.execute("CREATE TABLE agent_jobs (assignment_id TEXT, run_id TEXT, state TEXT, "
                   "usage TEXT, model TEXT)")
        db.execute("CREATE TABLE ctf_agent_reports (assignment_id TEXT, run_id TEXT)")
        db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT)")
        for index in range(8):
            run_id = f"{index + 1:032x}"
            db.execute("INSERT INTO codex_sessions VALUES (?,?)", (run_id, "held_out"))
            assignment_id = f"assignment-{index}"
            db.execute("INSERT INTO agent_jobs VALUES (?,?,?,?,?)", (
                assignment_id, run_id, "completed", json.dumps({"input_tokens": 3, "output_tokens": 2}),
                "test-model"))
            db.execute("INSERT INTO ctf_agent_reports VALUES (?,?)", (assignment_id, run_id))
            db.execute("INSERT INTO agent_turn_reservations VALUES (?)", (run_id,))
            previous = ""
            for sequence, (status, detail) in enumerate([
                ("new", {}), ("executing", {"tool": "text"}),
                ("solved", {"verification": "local_fixture_oracle"}),
            ]):
                payload = json.dumps({"schema_version": 1, "run_id": run_id,
                                      "sequence": sequence, "status": status, "detail": detail})
                timestamp = f"2026-01-01T00:00:{sequence:02d}+00:00"
                digest = RunStore._digest(payload, timestamp, previous)
                db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (
                    run_id, sequence, payload, timestamp, previous, digest))
                previous = digest
    runs = [{"task_id": f"task{index // 4}", "repetition": (index // 2) % 2,
             "arm": ("full" if index % 2 == 0 else "single_agent"),
             "run_id": f"{index + 1:032x}"} for index in range(8)]
    budget = {"model_calls": 4, "tokens": 100, "actions": 4,
              "seconds": 60.0, "cost_usd": None}
    manifest = ExportManifest.model_validate({
        "schema_version": 1, "study_id": "synthetic-export", "measurement": "synthetic_fixture",
        "model_pin": "test-model", "runtime_pin": "test-runtime", "seed": 1,
        "repetitions": 2, "arms": ["full", "single_agent"], "baseline": "single_agent",
        "budgets": {"full": budget, "single_agent": budget},
        "tasks": [{"task_id": f"task{i}", "category": "crypto", "difficulty": "easy",
                   "split": "held_out", "exposure": "unseen",
                   "solvability_control_verified": True} for i in range(2)],
        "runs": runs,
    })
    return dbpath, manifest


def test_export_derives_outcome_and_resources(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    study = export(manifest, database)
    assert len(study.trials) == 8
    assert all(trial.oracle == "protected_fixture" and trial.oracle_verified
               and trial.workflow_complete and trial.failure == "none"
               and trial.model_calls == 1 and trial.actions == 1
               and trial.tokens == 5 and trial.cost_usd is None
               for trial in study.trials)
    assert reconcile_evidence(study, database)["protected_fixture_verified_trials"] == 8


def test_export_rejects_corrupt_chain(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE events SET digest='invalid' WHERE run_id=? AND sequence=1",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="event chain is corrupt"):
        export(manifest, database)


def test_export_rejects_split_and_matrix_mismatch(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET evaluation_split='development' WHERE run_id=?",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="split"):
        export(manifest, database)
    data = manifest.model_dump()
    data["runs"] = data["runs"][:-1]
    with pytest.raises(ValueError, match="at least 8"):
        ExportManifest.model_validate(data)


def test_export_does_not_trust_missing_usage_or_unverified_end(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET usage=NULL WHERE run_id=?", (manifest.runs[0].run_id,))
    study = export(manifest, database)
    assert study.trials[0].tokens is None


def test_real_model_pin_must_match_job_records(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    data = manifest.model_dump()
    data["measurement"] = "real_model"
    real_manifest = ExportManifest.model_validate(data)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET model='other-model' WHERE run_id=?",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="model pin"):
        export(real_manifest, database)


def test_verified_event_without_completed_report_does_not_score(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM ctf_agent_reports WHERE run_id=?", (manifest.runs[0].run_id,))
    trial = export(manifest, database).trials[0]
    assert trial.oracle_verified is True
    assert trial.workflow_complete is False
    assert trial.failure == "unverified"
