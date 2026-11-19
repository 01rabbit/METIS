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
