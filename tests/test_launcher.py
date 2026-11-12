import subprocess
from pathlib import Path


def test_launcher_exposes_safe_interactive_start_prompt():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([str(root / "metis-codex"), "--print-prompt"],
                            cwd=root, text=True, capture_output=True, check=True)
    assert "問題URL" in result.stdout
    assert "ローカル配布ファイル" in result.stdout
    assert "metis web auth" in result.stdout
    assert "認証値そのものを会話へ貼るよう求めず" in result.stdout
