import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = runpy.run_path(str(ROOT / "scripts" / "setup.py"))


def _venv(root: Path, interpreter: str) -> None:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").write_text("")
    (bin_dir / "metis").write_text(f"#!{interpreter}\nimport metis\n")


def test_moved_virtualenv_is_detected(tmp_path):
    here = tmp_path / "here"
    _venv(here, str(here / ".venv" / "bin" / "python"))
    assert SETUP["environment_is_stale"](here) is False
    moved = tmp_path / "moved"
    _venv(moved, "/Users/old/METIS/.venv/bin/python")
    assert SETUP["environment_is_stale"](moved) is True
    assert SETUP["environment_is_stale"](tmp_path / "none") is False


def test_claude_code_settings_are_repointed_and_domains_kept(tmp_path):
    for name in ("skills/metis", "agents", "commands"):
        (tmp_path / "integrations" / "claude-code" / name).mkdir(parents=True)
    (tmp_path / "integrations" / "claude-code" / "agents" / "ctf-pwn.md").write_text("agent")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(json.dumps({"sandbox": {
        "network": {"allowedDomains": ["ksnctf.sweetduet.info"]},
        "excludedCommands": ["/Users/old/METIS/.venv/bin/metis sandbox *", "npm test"]}}))
    result = SETUP["configure_claude_code"](tmp_path)
    settings = json.loads((claude / "settings.local.json").read_text())["sandbox"]
    assert result["removed_stale_paths"] == ["/Users/old/METIS/.venv/bin/metis sandbox *"]
    assert settings["network"]["allowedDomains"] == ["ksnctf.sweetduet.info"]
    assert "npm test" in settings["excludedCommands"]
    assert str(tmp_path / ".venv" / "bin" / "metis") + " sandbox *" in settings["excludedCommands"]
    assert (claude / "agents" / "ctf-pwn.md").read_text() == "agent"
    again = SETUP["configure_claude_code"](tmp_path)  # idempotent
    assert again["removed_stale_paths"] == []
    assert len(json.loads((claude / "settings.local.json").read_text())["sandbox"]["excludedCommands"]) == 4


def test_start_repairs_a_moved_virtualenv(tmp_path):
    start = runpy.run_path(str(ROOT / "start"))
    _venv(tmp_path, "/Users/old/METIS/.venv/bin/python")
    assert start["venv_moved"](tmp_path) is True


def _fake_tee(results, seen):
    def fake(command, root, environment):
        seen.append(dict(environment))
        return results.pop(0)
    return fake


def test_uv_retries_once_on_certificate_error(monkeypatch, capsys):
    run = SETUP["run_uv_sync"]
    monkeypatch.delenv("UV_SYSTEM_CERTS", raising=False)
    monkeypatch.delenv("UV_NATIVE_TLS", raising=False)
    seen = []
    run.__globals__["_run_tee"] = _fake_tee([(2, "invalid peer certificate: OSStatus -26276"), (0, "")], seen)
    run(["uv"], Path("."), {"UV_SYSTEM_CERTS": "true"})
    assert len(seen) == 2
    assert seen[1]["UV_SYSTEM_CERTS"] == "false" and seen[1]["UV_NATIVE_TLS"] == "false"
    assert "retrying once" in capsys.readouterr().out


def test_uv_does_not_retry_unrelated_failure_or_user_env(monkeypatch):
    import subprocess

    import pytest
    run = SETUP["run_uv_sync"]
    monkeypatch.delenv("UV_SYSTEM_CERTS", raising=False)
    monkeypatch.delenv("UV_NATIVE_TLS", raising=False)
    seen = []
    run.__globals__["_run_tee"] = _fake_tee([(1, "no such package")], seen)
    with pytest.raises(subprocess.CalledProcessError):
        run(["uv"], Path("."), {})
    assert len(seen) == 1
    monkeypatch.setenv("UV_NATIVE_TLS", "true")
    seen.clear()
    run.__globals__["_run_tee"] = _fake_tee([(2, "invalid peer certificate")], seen)
    with pytest.raises(subprocess.CalledProcessError):
        run(["uv"], Path("."), {})
    assert len(seen) == 1


def test_uv_fails_when_retry_fails_too(monkeypatch, capsys):
    import subprocess

    import pytest
    run = SETUP["run_uv_sync"]
    monkeypatch.delenv("UV_SYSTEM_CERTS", raising=False)
    monkeypatch.delenv("UV_NATIVE_TLS", raising=False)
    seen = []
    run.__globals__["_run_tee"] = _fake_tee([(2, "invalid peer certificate"), (3, "still bad")], seen)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run(["uv"], Path("."), {})
    assert caught.value.returncode == 3 and len(seen) == 2
    assert "failed twice" in capsys.readouterr().err
