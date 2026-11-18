"""Case journal and repository guard."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from metis.blue import journal

ROOT = Path(__file__).resolve().parent.parent


def _run(root, *argv):
    parser = journal.build_parser()
    return journal.run(parser.parse_args(list(argv)), root)


def test_journal_records_findings_and_closes(tmp_path, capsys):
    root = tmp_path / "journal"
    _run(root, "open", "--case", "Beacon alert", "--type", "ctf", "--objective", "find the C2 host")
    case = capsys.readouterr().out.strip()
    assert case.endswith("-beacon-alert") and oct(root.stat().st_mode & 0o777) == "0o700"
    _run(root, "query", "--case", case, "--platform", "zeek", "--query", "conn.log by dst", "--hits", "3")
    _run(root, "finding", "--case", case, "--summary", "60 s beacon",
         "--evidence", "conn.log 10.0.0.5 to 198.51.100.7:443", "--confidence", "high")
    _run(root, "close", "--case", case, "--outcome", "solved", "--summary", "beacon confirmed")
    cover = (root / case / "case.md").read_text()
    assert "| outcome | solved |" in cover and "60 s beacon" in cover
    assert json.loads((root / case / "meta.json").read_text())["outcome"] == "solved"
    assert case in (root / "INDEX.md").read_text()


@pytest.mark.parametrize("text", ["password=hunter2secret", "flag{real_answer_here}",
                                  "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123"])
def test_journal_refuses_credentials_and_answers_without_echoing(tmp_path, capsys, text):
    root = tmp_path / "journal"
    _run(root, "open", "--case", "x1")
    case = capsys.readouterr().out.strip()
    with pytest.raises(SystemExit) as raised:
        _run(root, "note", "--case", case, "--text", text)
    assert text not in str(raised.value)
    assert (root / case / "timeline.jsonl").read_text() == ""


def test_journal_accepts_answer_format_examples(tmp_path, capsys):
    root = tmp_path / "journal"
    _run(root, "open", "--case", "x2")
    case = capsys.readouterr().out.strip()
    _run(root, "note", "--case", case, "--text", "answers look like flag{...}")
    assert "flag{...}" in (root / case / "timeline.jsonl").read_text()


def _guard(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_repo", ROOT / "scripts" / "check_repo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(module, "ROOT", repo)
    return module, repo


def test_guard_refuses_private_paths_secrets_and_answers(tmp_path, monkeypatch):
    module, repo = _guard(tmp_path, monkeypatch)
    (repo / "notes.md").write_text("ok: flag{...}\n")
    (repo / "leak.md").write_text("the answer is CTF{live_value_1}\n")
    (repo / "key.txt").write_text("AKIA" + "ABCDEFGHIJKLMNOP\n")
    (repo / ".metis-state").mkdir()
    (repo / ".metis-state" / "x.txt").write_text("state\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    errors = module.check(staged=True)
    assert any("answer-shaped" in e and "leak.md" in e for e in errors)
    assert any("secret-shaped" in e and "key.txt" in e for e in errors)
    assert any("private or runtime path" in e for e in errors)
    assert not any("notes.md" in e for e in errors)
    assert all("live_value" not in e and "ABCDEFGH" not in e for e in errors)


def test_guard_flags_staged_snapshot_that_differs(tmp_path, monkeypatch):
    module, repo = _guard(tmp_path, monkeypatch)
    (repo / "a.md").write_text("clean\n")
    subprocess.run(["git", "add", "a.md"], cwd=repo, check=True)
    (repo / "a.md").write_text("edited after staging\n")
    assert any("differs from the worktree" in e for e in module.check(staged=True))
    monkeypatch.setenv("METIS_DENY_PATTERN", "teamsecretname")
    (repo / "b.md").write_text("contact TeamSecretName\n")
    subprocess.run(["git", "add", "b.md"], cwd=repo, check=True)
    assert any("prohibited identifier: b.md" in e for e in module.check(staged=True))


def test_metis_journal_cli_is_wired(tmp_path):
    result = subprocess.run([str(ROOT / ".venv" / "bin" / "metis"), "journal", "--root", str(tmp_path / "j"),
                             "open", "--case", "cli"], check=False, capture_output=True, text=True)
    if result.returncode == 127 or not (ROOT / ".venv" / "bin" / "metis").exists():
        pytest.skip("metis entry point not installed")
    assert result.returncode == 0 and result.stdout.strip().endswith("-cli")
