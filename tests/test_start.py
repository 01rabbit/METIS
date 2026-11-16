import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_start_lists_supported_agents():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([str(root / "start"), "--list"], cwd=root, text=True,
                            capture_output=True, check=True)
    for name in ("codex", "claude", "gemini", "opencode", "aider"):
        assert f"{name}:" in result.stdout


def test_start_routes_codex_to_hardened_adapter(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    called = {}

    def discover(name):
        return "/opt/codex/bin/codex" if name == "codex" else None

    def capture(executable, arguments):
        called.update(executable=executable, arguments=arguments)
        raise RuntimeError("captured exec")

    monkeypatch.setattr(sys, "argv", ["start"])
    monkeypatch.setattr("shutil.which", discover)
    monkeypatch.setattr("os.execv", capture)
    with pytest.raises(RuntimeError, match="captured exec"):
        runpy.run_path(str(root / "start"), run_name="__main__")
    assert called["executable"] == str(root / "metis-codex")
    assert called["arguments"] == [str(root / "metis-codex")]


def test_start_gives_claude_the_metis_startup_prompt(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    called = {}

    def discover(name):
        return "/opt/claude/bin/claude" if name == "claude" else None

    def capture(executable, arguments):
        called.update(executable=executable, arguments=arguments)
        raise RuntimeError("captured exec")

    monkeypatch.setattr(sys, "argv", ["start", "--agent", "claude", "--model", "opus"])
    monkeypatch.setattr("shutil.which", discover)
    monkeypatch.setattr("os.execv", capture)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)  # never bootstrap in tests
    with pytest.raises(RuntimeError, match="captured exec"):
        runpy.run_path(str(root / "start"), run_name="__main__")
    assert called["executable"] == "/opt/claude/bin/claude"
    assert called["arguments"][1:3] == ["--model", "opus"]
    assert "SKILL.md" in called["arguments"][-1]


def test_claude_subagents_are_well_formed():
    root = Path(__file__).resolve().parents[1]
    agents = sorted((root / "integrations/claude-code/agents").glob("*.md"))
    names = set()
    for path in agents:
        header = path.read_text().split("---")[1]
        fields = dict(line.split(": ", 1) for line in header.strip().splitlines())
        assert fields["name"] == path.stem
        assert fields["model"] in {"haiku", "sonnet", "opus", "inherit"}
        assert "metis web submit" in path.read_text()  # explicitly forbidden in each executor
        names.add(fields["name"])
    skill = (root / "integrations/claude-code/skills/metis/SKILL.md").read_text()
    for name in names:
        assert f"`{name}`" in skill
    assert {"ctf-triage", "ctf-critic", "ctf-pwn"} <= names
