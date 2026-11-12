import hashlib
import json
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
