import hashlib
import json
import os
import subprocess
import sys

import pytest

from metis.core.codex_session import CodexSession, transform
from metis.core.contracts import ChallengeManifest, RunStatus
from metis.core.runtime import ToolRequest


def test_codex_native_demo_without_api_or_docker(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("METIS_OPENAI_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("native tools must not start any process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    database = tmp_path / "sessions.sqlite"
    session = CodexSession(database)
    for context in session.demo():
        description = context["challenge"]["description"]
        payload = description.rsplit(": ", 1)[1]
        tool = "base64_decode" if "base64" in description else "hex_decode"
        run_id = context["run_id"]
        result = session.act(run_id, ToolRequest(tool=tool, data=payload))
        assert result["ok"]
        answer = result["output"]
        assert not session.submit(run_id, "METIS{wrong}")["verified"]
        assert session.submit(run_id, answer)["verified"]
        assert session.context(run_id)["status"] == "solved"
        assert answer not in session.store.export_jsonl(run_id)
        assert answer.encode() not in database.read_bytes()
        with pytest.raises(ValueError, match="not awaiting"):
            session.act(run_id, ToolRequest(tool=tool, data=payload))


def test_native_scope_budget_and_unverified_candidate(tmp_path):
    session = CodexSession(tmp_path / "sessions.sqlite")
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "local", "title": "Local", "description": "Solve local data",
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "local"},
    })
    context = session.start(manifest, max_actions=1)
    assert not session.submit(context["run_id"], "anything")["verified"]
    with pytest.raises(ValueError, match="budget exhausted"):
        session.act(context["run_id"], ToolRequest(tool="sha256", data="x"))
    assert session.context(context["run_id"])["status"] == "exhausted"
    cancelled = session.start(manifest)
    assert session.cancel(cancelled["run_id"])["status"] == "cancelled"
    bad = manifest.model_dump()
    bad["scope"]["allowed_endpoints"] = [{"hostname": "localhost", "port": 80}]
    scoped = session.start(ChallengeManifest.model_validate(bad))
    assert scoped["challenge"]["scope"]["allowed_endpoints"]
    assert scoped["network_tools"] == []


def test_native_invalid_inputs_cannot_be_executed():
    assert not transform(ToolRequest(tool="shell", data="touch /tmp/not-allowed")).ok
    assert not transform(ToolRequest(tool="hex_decode", data="!bad")).ok
    assert not transform(ToolRequest(tool="sha256", data="あ" * 30_000)).ok
    assert transform(ToolRequest(tool="sha256", data="fixture")).output == hashlib.sha256(
        b"fixture",
    ).hexdigest()


def test_codex_cli_across_processes(tmp_path):
    command = [sys.executable, "-m", "metis.cli", "codex", "--database",
               str(tmp_path / "session.sqlite")]
    demo = subprocess.run([*command, "demo"], capture_output=True, text=True, check=True)
    context = json.loads(demo.stdout)["sessions"][0]
    payload = context["challenge"]["description"].rsplit(": ", 1)[1]
    action = subprocess.run([*command, "act", context["run_id"], "base64_decode"],
                            input=payload, capture_output=True, text=True, check=True)
    answer = json.loads(action.stdout)["output"]
    result = subprocess.run([*command, "submit", context["run_id"]], input=answer,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["verified"]


def test_recovery_preserves_budget_and_never_fabricates_verification(tmp_path):
    session = CodexSession(tmp_path / "session.sqlite")
    context = session.demo()[0]
    run_id = context["run_id"]
    session._reserve(run_id, "native_data_transform")
    assert session.context(run_id)["status"] == "executing"
    restored = CodexSession(tmp_path / "session.sqlite")
    recovered = restored.recover(run_id)
    assert recovered["status"] == "planning"
    assert recovered["actions_remaining"] == 39
    assert not any(event.status == RunStatus.SOLVED for event in restored.store.read(run_id))
    assert any(row["run_id"] == run_id for row in restored.board())
    restored._reserve(run_id, "native_data_transform")
    assert restored.cancel(run_id)["status"] == "cancelled"
    assert restored.recover(run_id)["status"] == "cancelled"


def test_emergency_stop_survives_controller_restart_without_resuming_work(tmp_path):
    database = tmp_path / "session.sqlite"
    controller = CodexSession(database)
    run_id = controller.demo()[0]["run_id"]

    # Model an operation reserved by the controller when the operator stops it.
    controller._reserve(run_id, "native_data_transform")
    before_stop = controller.context(run_id)
    assert before_stop["status"] == "executing"
    assert before_stop["actions_remaining"] == 39

    stopped = controller.cancel(run_id)
    assert stopped["status"] == "cancelled"

    # A newly constructed controller represents a process restart over the same DB.
    restarted = CodexSession(database)
    recovered = restarted.recover(run_id)
    assert recovered["status"] == "cancelled"
    assert recovered["actions_remaining"] == 39
    assert not any(event.status == RunStatus.SOLVED for event in restarted.store.read(run_id))
    assert restarted.recover(run_id)["status"] == "cancelled"


def test_intake_accepts_explicit_path_through_symlinked_directory(tmp_path):
    # macOS exposes /tmp as a symlink to /private/tmp.
    real = tmp_path / "private-tmp"
    real.mkdir()
    (real / "hello.sh").write_text("#!/bin/sh\necho hi\n")
    link = tmp_path / "tmp"
    link.symlink_to(real, target_is_directory=True)
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    context = session.intake(title="t", description="d", paths=[link / "hello.sh"])
    assert context["challenge"]["artifacts"] == ["00-hello.sh"]
    fifo = real / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        session.intake(title="t", description="d", paths=[link / "pipe"])


def test_wall_clock_starts_at_first_action_and_extend_resumes(tmp_path, monkeypatch):
    import time as time_module
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    note = tmp_path / "n.txt"
    note.write_text("x")
    run_id = session.intake(title="t", description="d", paths=[note], wall_seconds=60)["run_id"]
    base = time_module.time()
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 3600)
    # An hour after intake with no action taken, the full budget is still available.
    context = session.context(run_id)
    assert context["seconds_remaining"] == 60 and context["budget"]["clock_started"] is False
    session.act(run_id, ToolRequest(tool="sha256", data="a"))
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 3600 + 61)
    with pytest.raises(ValueError, match="exhausted"):
        session.act(run_id, ToolRequest(tool="sha256", data="b"))
    assert session.context(run_id)["status"] == "exhausted"
    resumed = session.extend(run_id, seconds=600, actions=10)
    assert resumed["status"] == "planning" and resumed["seconds_remaining"] > 500
    assert session.act(run_id, ToolRequest(tool="sha256", data="c"))["ok"] is True
    with pytest.raises(ValueError):
        session.extend(run_id, seconds=10 * 86_400)
    session.cancel(run_id)
    with pytest.raises(ValueError):
        session.extend(run_id, seconds=60)


def test_extend_after_long_expiry_counts_from_now(tmp_path, monkeypatch):
    import time as time_module
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    note = tmp_path / "n.txt"
    note.write_text("x")
    run_id = session.intake(title="t", description="d", paths=[note], wall_seconds=7200)["run_id"]
    base = time_module.time()
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base)
    session.act(run_id, ToolRequest(tool="sha256", data="a"))
    # 3.46 hours after the first action the 2-hour budget is long gone.
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 12_456)
    with pytest.raises(ValueError, match="exhausted"):
        session.act(run_id, ToolRequest(tool="sha256", data="b"))
    resumed = session.extend(run_id, seconds=3600)
    assert resumed["status"] == "planning" and 3590 <= resumed["seconds_remaining"] <= 3600


def test_state_survives_moving_the_checkout(tmp_path):
    import shutil as shutil_module
    import sqlite3
    old = tmp_path / "old" / ".metis-state"
    session = CodexSession(old / "metis.sqlite")
    note = tmp_path / "cipher.txt"
    note.write_text("Uryyb")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    with sqlite3.connect(old / "metis.sqlite") as db:
        stored = db.execute("SELECT artifact_root FROM codex_sessions").fetchone()[0]
    assert not stored.startswith("/")  # stored relative to the state directory
    shutil_module.move(str(tmp_path / "old"), str(tmp_path / "new"))
    moved = CodexSession(tmp_path / "new" / ".metis-state" / "metis.sqlite")
    assert moved.artifact(run_id, "00-cipher.txt", "text")["ok"] is True


def test_legacy_absolute_artifact_roots_are_migrated(tmp_path):
    import shutil as shutil_module
    import sqlite3
    old = tmp_path / "old" / ".metis-state"
    session = CodexSession(old / "metis.sqlite")
    note = tmp_path / "cipher.txt"
    note.write_text("Uryyb")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    root = session.artifact_root(run_id)
    with sqlite3.connect(old / "metis.sqlite") as db:  # simulate a database written by an older METIS
        db.execute("UPDATE codex_sessions SET artifact_root=?", (str(root),))
    shutil_module.move(str(tmp_path / "old"), str(tmp_path / "new"))
    moved = CodexSession(tmp_path / "new" / ".metis-state" / "metis.sqlite")
    assert moved.artifact_root(run_id) == (tmp_path / "new" / ".metis-state" / root.name).resolve()
    assert moved.artifact(run_id, "00-cipher.txt", "text")["ok"] is True


def test_legacy_database_split_defaults_to_unlisted(tmp_path):
    import sqlite3

    database = tmp_path / "legacy.sqlite"
    session = CodexSession(database)
    note = tmp_path / "cipher.txt"
    note.write_text("synthetic")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE codex_sessions DROP COLUMN evaluation_split")
    migrated = CodexSession(database)
    assert migrated.context(run_id)["evaluation_split"] == "unlisted"
