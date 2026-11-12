import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_launcher_exposes_safe_interactive_start_prompt():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([str(root / "metis-codex"), "--print-prompt"],
                            cwd=root, text=True, capture_output=True, check=True)
    assert "問題URL" in result.stdout
    assert "ローカル配布ファイル" in result.stdout
    assert "metis web auth" in result.stdout
    assert "認証値そのものを会話へ貼るよう求めず" in result.stdout
    assert "Daybreakをオーケストレーター" in result.stdout
    assert "通常2〜4担当" in result.stdout


def test_launcher_enables_daybreak_and_multi_agent(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    called = {}

    def capture(executable, arguments):
        called["executable"] = executable
        called["arguments"] = arguments
        raise RuntimeError("captured exec")

    monkeypatch.setattr(sys, "argv", ["metis-codex", "--skip-setup"])
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("os.execv", capture)
    with pytest.raises(RuntimeError, match="captured exec"):
        runpy.run_path(str(root / "metis-codex"), run_name="__main__")
    assert called["executable"] == "/usr/bin/codex"
    assert "--approve-for-me" in called["arguments"]
    assert ["--enable", "cli_daybreak"] == called["arguments"][4:6]
    assert ["--enable", "multi_agent"] == called["arguments"][6:8]
