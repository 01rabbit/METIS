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


def _launch(monkeypatch, help_text, features, env=None):
    root = Path(__file__).resolve().parents[1]
    called = {}

    def capture(executable, arguments):
        called["executable"] = executable
        called["arguments"] = arguments
        raise RuntimeError("captured exec")

    def fake_run(command, **kwargs):
        if command[1:] == ["--help"]:
            return subprocess.CompletedProcess(command, 0, help_text, "")
        if command[1:] == ["features", "list"]:
            if features is None:
                return subprocess.CompletedProcess(command, 2, "", "unknown command")
            return subprocess.CompletedProcess(command, 0, features, "")
        raise AssertionError(command)

    monkeypatch.setattr(sys, "argv", ["metis-codex", "--skip-setup"])
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os.execv", capture)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="captured exec"):
        runpy.run_path(str(root / "metis-codex"), run_name="__main__")
    assert called["executable"] == "/usr/bin/codex"
    return called["arguments"]


def test_launcher_enables_known_features(monkeypatch):
    arguments = _launch(monkeypatch, "  --approve-for-me  ...",
                        "cli_daybreak  experimental  false\nmulti_agent  stable  true\n")
    assert "--approve-for-me" in arguments
    assert ["--enable", "cli_daybreak", "--enable", "multi_agent"] == arguments[4:8]


def test_launcher_skips_unknown_features_and_flags(monkeypatch, capsys):
    arguments = _launch(monkeypatch, "usage: codex [OPTIONS]", "multi_agent  stable  true\n")
    assert "cli_daybreak" not in arguments and "--approve-for-me" not in arguments
    assert ["--enable", "multi_agent"] == arguments[3:5]
    assert "cli_daybreak" in capsys.readouterr().err


def test_launcher_starts_without_feature_listing(monkeypatch):
    arguments = _launch(monkeypatch, "", None)
    assert "--enable" not in arguments and arguments[-1].startswith("METIS")


def test_launcher_feature_override(monkeypatch):
    arguments = _launch(monkeypatch, "", "multi_agent  stable  true\nnew_flag  beta  false\n",
                        env={"METIS_CODEX_FEATURES": "new_flag"})
    assert ["--enable", "new_flag"] == arguments[3:5] and "multi_agent" not in arguments
