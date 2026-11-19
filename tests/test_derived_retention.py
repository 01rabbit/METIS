"""Age-based removal never touches original inputs or active runs."""
import json
import sqlite3
import sys
import time

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.contracts import RunStatus
from metis.core.derived_retention import retain_derived


def test_retention_preview_apply_and_active_run_block(tmp_path, monkeypatch, capsys):
    database = tmp_path / "state.sqlite"
    original = tmp_path / "input.txt"
    original.write_text("original")
    session = CodexSession(database)
    old = session.intake(title="old", description="fixture", paths=[original])["run_id"]
    recent = session.intake(title="recent", description="fixture", paths=[original])["run_id"]
    active = session.intake(title="active", description="fixture", paths=[original])["run_id"]
    old_artifact = session.store_artifact(old, b"old output")
    recent_artifact = session.store_artifact(recent, b"new output")
    active_artifact = session.store_artifact(active, b"active output")
    session._emit(old, RunStatus.CANCELLED)
    old_root = session.artifact_root(old)
    recent_root = session.artifact_root(recent)
    active_root = session.artifact_root(active)
    assert old_root and recent_root and active_root
    session._emit(active, RunStatus.EXECUTING)
    now = time.time()
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET started=? WHERE run_id IN (?, ?)",
                   (now - 31 * 86_400, old, active))

    preview = retain_derived(database, older_than_days=30, now=now)
    assert preview["applied"] is False and preview["selected_runs"] == 2
    assert {row["run_id"]: row["status"] for row in preview["results"]} == {
        old: "preview", active: "blocked"}
    assert (old_root / old_artifact).exists()
    assert (recent_root / recent_artifact).exists()
    assert (active_root / active_artifact).exists()

    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(database),
                                      "retention-derived", "--older-than-days", "30", "--apply"])
    assert main() == 2
    applied = json.loads(capsys.readouterr().out)
    assert {row["run_id"]: row["status"] for row in applied["results"]} == {
        old: "applied", active: "blocked"}
    assert not (old_root / old_artifact).exists()
    assert (old_root / "00-input.txt").read_text() == "original"
    assert (recent_root / recent_artifact).exists()
    assert (active_root / active_artifact).exists()
    repeated = retain_derived(database, older_than_days=30, now=now)
    assert next(row for row in repeated["results"] if row["run_id"] == old)["files"] == []


def test_retention_age_bounds(tmp_path):
    for days in (0, 3651):
        with pytest.raises(ValueError, match="retention age"):
            retain_derived(tmp_path / "missing.sqlite", older_than_days=days)


def test_retention_blocks_old_planning_and_extendable_exhausted(tmp_path, monkeypatch, capsys):
    database = tmp_path / "state.sqlite"
    original = tmp_path / "input.txt"
    original.write_text("original")
    session = CodexSession(database)
    planning = session.intake(title="planning", description="fixture", paths=[original])["run_id"]
    exhausted = session.intake(title="exhausted", description="fixture", paths=[original])["run_id"]
    planning_artifact = session.store_artifact(planning, b"pending work")
    exhausted_artifact = session.store_artifact(exhausted, b"pending extension")
    planning_root = session.artifact_root(planning)
    exhausted_root = session.artifact_root(exhausted)
    assert planning_root and exhausted_root
    session._emit(exhausted, RunStatus.EXHAUSTED, reason="budget_limit")
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET started=? WHERE run_id IN (?, ?)",
                   (time.time() - 31 * 86_400, planning, exhausted))
    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(database),
                                      "retention-derived", "--older-than-days", "30", "--apply"])
    assert main() == 2
    result = json.loads(capsys.readouterr().out)
    assert {row["run_id"]: row["status"] for row in result["results"]} == {
        planning: "blocked", exhausted: "blocked"}
    assert (planning_root / planning_artifact).read_bytes() == b"pending work"
    assert (exhausted_root / exhausted_artifact).read_bytes() == b"pending extension"
    assert session.extend(exhausted, actions=1)["status"] == RunStatus.PLANNING.value
    assert (exhausted_root / exhausted_artifact).exists()


def test_retention_rejects_oversized_selection_before_purge(tmp_path, monkeypatch):
    database = tmp_path / "state.sqlite"
    CodexSession(database)
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO codex_sessions "
            "(run_id, manifest, started, max_actions, wall_seconds) VALUES (?, '{}', 1, 1, 1)",
            [(f"run-{index:03d}",) for index in range(101)],
        )
    monkeypatch.setattr(CodexSession, "purge_derived",
                        lambda *args, **kwargs: pytest.fail("purge called before limit check"))
    with pytest.raises(ValueError, match="exceeds 100"):
        retain_derived(database, older_than_days=30, apply=True, now=100 * 86_400)


def _aged_run_with_derived_count(database, count, started):
    from uuid import uuid4

    source = database.parent / f"input-{count}-{started}.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="bounded retention", description="fixture",
                            paths=[source])["run_id"]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    derived_dir = root / ".metis-derived"
    derived_dir.mkdir(mode=0o700)
    paths = [f".metis-derived/{uuid4().hex}.bin" for _ in range(count)]
    for relative in paths:
        (root / relative).write_bytes(b"generated")
    manifest = session.context(run_id)["challenge"]
    manifest["artifacts"].extend(paths)
    from metis.core.contracts import ChallengeManifest
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET manifest=?, started=? WHERE run_id=?",
                   (ChallengeManifest.model_validate(manifest).model_dump_json(), started, run_id))
    return session, run_id, root, paths


def test_retention_artifact_count_boundary_is_previewable(tmp_path):
    database = tmp_path / "state.sqlite"
    now = 100 * 86_400
    _session, run_id, _root, _paths = _aged_run_with_derived_count(
        database, 100, now - 31 * 86_400)

    preview = retain_derived(database, older_than_days=30, now=now)
    result = next(row for row in preview["results"] if row["run_id"] == run_id)
    assert preview["artifact_limit_per_run"] == 100
    assert result["status"] == "preview"
    assert len(result["files"]) == 100


def test_retention_overflow_apply_preflights_batch_and_never_unlinks(tmp_path, monkeypatch, capsys):
    database = tmp_path / "state.sqlite"
    now = 100 * 86_400
    first_session, first_run, first_root, first_paths = _aged_run_with_derived_count(
        database, 1, now - 32 * 86_400)
    _session, overflow_run, overflow_root, overflow_paths = _aged_run_with_derived_count(
        database, 101, now - 31 * 86_400)
    before_manifest = first_session._session(first_run)[0]
    overflow_session = CodexSession(database)
    before_overflow_manifest = overflow_session._session(overflow_run)[0]

    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(database),
                                      "retention-derived", "--older-than-days", "30", "--apply"])
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    rows = {row["run_id"]: row for row in report["results"]}
    assert report["artifact_limit_per_run"] == 100
    assert rows[first_run]["status"] == "not_applied"
    assert rows[first_run]["artifact_count"] == 1
    assert rows[overflow_run]["status"] == "overflow"
    assert rows[overflow_run]["artifact_count"] == 101
    assert rows[overflow_run]["artifact_limit"] == 100
    assert "files" not in rows[overflow_run]
    assert not any(path in json.dumps(rows[overflow_run]) for path in overflow_paths)
    assert first_session._session(first_run)[0] == before_manifest
    assert overflow_session._session(overflow_run)[0] == before_overflow_manifest
    assert all((first_root / path).is_file() for path in first_paths)
    assert all((overflow_root / path).is_file() for path in overflow_paths)
