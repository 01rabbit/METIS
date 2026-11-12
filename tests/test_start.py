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
