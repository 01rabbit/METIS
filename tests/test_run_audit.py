import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.runtime import ToolRequest
from metis.core.store import RunStore


def audit(database: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "metis.cli", "audit", run_id, "--database", str(database)],
        check=False, capture_output=True, text=True,
    )


def start(session: CodexSession) -> str:
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "audit-fixture", "title": "private-title-omitted",
        "description": "private-description-omitted",
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "audit-fixture"},
    })
    return str(session.start(manifest, max_actions=2, wall_seconds=60)["run_id"])


def test_audit_budget_counts_failed_and_interrupted_reservations_and_extension(tmp_path):
    database = tmp_path / "runs.sqlite"
    session = CodexSession(database)
    run_id = start(session)
    initial = json.loads(audit(database, run_id).stdout)
    assert initial["codex_budget"] == {
        "max_actions": 2, "wall_seconds": 60, "actions_charged": 0, "actions_remaining": 2,
    }

    assert not session.act(run_id, ToolRequest(tool="hex_decode", data="invalid"))["ok"]
    session.extend(run_id, actions=3)
    # Model an interrupted reservation before its OBSERVING event; no worker is launched.
    session._reserve(run_id, "fixture_interruption", private="private-detail-omitted")
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "executing"
    assert summary["codex_budget"] == {
        "max_actions": 5, "wall_seconds": 60, "actions_charged": 2, "actions_remaining": 3,
    }
    assert "private-" not in result.stdout + result.stderr
    assert audit(database, run_id).stdout == result.stdout
    assert database.read_bytes() == before


@pytest.mark.parametrize("with_session_table", [False, True])
def test_audit_budget_is_unavailable_for_non_codex_run(tmp_path, with_session_table):
    database = tmp_path / "runs.sqlite"
    if with_session_table:
        start(CodexSession(database))
    store = RunStore(database)
    store.append(RunEvent(run_id="plain", sequence=0, status=RunStatus.NEW))
    result = audit(database, "plain")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["codex_budget"] is None


@pytest.mark.parametrize("invalid", [0, -1, 1.5, "private-budget-omitted"])
@pytest.mark.parametrize("column", ["max_actions", "wall_seconds"])
def test_audit_budget_rejects_invalid_configuration_without_echo_or_write(tmp_path, invalid, column):
    database = tmp_path / "runs.sqlite"
    run_id = start(CodexSession(database))
    with sqlite3.connect(database) as db:
        db.execute(f"UPDATE codex_sessions SET {column}=? WHERE run_id=?", (invalid, run_id))
    before = database.read_bytes()
    result = audit(database, run_id)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unavailable or corrupt" in result.stderr
    assert "private-budget-omitted" not in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before
