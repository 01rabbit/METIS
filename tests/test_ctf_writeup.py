import hashlib
import json
import sys
from pathlib import Path

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_writeup import WriteupBook, WriteupInput

ANSWER = "FLAG_writeup_mock_answer"


@pytest.fixture
def solved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = tmp_path / ".metis-state" / "metis.sqlite"
    session = CodexSession(database)
    note = tmp_path / "cipher.txt"
    note.write_text("Uryyb")
    run_id = session.intake(title="Easy Cipher", description="decode", paths=[note], categories=["crypto"],
                            evaluation_split="practice",
                            commitment=hashlib.sha256(ANSWER.encode()).hexdigest())["run_id"]
    assert session.submit(run_id, ANSWER)["verified"] is True
    board = ContestBoard(database)
    contest_id = board.create({"name": "ksnctf", "format": "jeopardy"})["contest_id"]
    board.add(contest_id, [{"challenge_id": "2", "title": "Easy Cipher", "category": "crypto", "points": 50},
                           {"challenge_id": "23", "title": "Villager B", "category": "pwn", "points": 450}])
    board.update(contest_id, "2", {"run_id": run_id, "state": "solved", "official_verified": True})
    work = tmp_path / ".metis-state" / "work"
    work.mkdir(parents=True)
    (work / "solve.py").write_text("print('rot13')\n")
    return database, contest_id, run_id


def _entry(run_id=None, **extra):
    return WriteupInput.model_validate({
        "summary": "ROT13で暗号化された文を復号する問題。",
        "analysis": "文字の出現頻度からシーザー系と判断した。",
        "solution": "```python\nimport codecs\nprint(codecs.decode(text, 'rot13'))\n```",
        "flag": ANSWER,
        "lessons": "まず古典暗号の総当たりを試す。",
        "tags": ["rot13", "classical"],
        "scripts": [".metis-state/work/solve.py"],
        "techniques": [
            {"title": "Classical shift cipher brute force", "category": "crypto",
             "summary": "Try all 26 Caesar shifts and pick readable English.",
             "conditions": "Ciphertext keeps letter case and spacing."},
            {"title": "Bad card", "category": "crypto", "summary": "The answer was " + ANSWER + "{x}",
             "conditions": "never"},
        ],
        **({"run_id": run_id} if run_id else {}), **extra})


def test_writeup_files_indexes_and_knowledge(solved, tmp_path):
    database, contest_id, _run_id = solved
    book = WriteupBook(database)
    result = book.save(contest_id, "2", _entry())
    path = Path(result["path"])
    assert path == Path("writeups/ksnctf/2-easy-cipher.md")
    text = path.read_text()
    # Issue #15: the answer lives in the vault; the write-up keeps a reference and the official check.
    assert ANSWER not in text and "`⟦answer:ksnctf/2-easy-cipher.md#flag⟧`" in text
    from metis.core.answer_vault import AnswerVault
    assert AnswerVault().get("ksnctf/2-easy-cipher.md#flag") == ANSWER
    assert result["answers_in_vault"] == 2  # the flag and the answer inside the refused card
    assert "解決済み（公式判定で正解" in text and "local_sha256_commitment" in text
    assert "## 解法" in text and "codecs.decode" in text
    assert "| 00-cipher.txt | 5 |" in text
    assert (tmp_path / "writeups/ksnctf/files/2/solve.py").read_text() == "print('rot13')\n"
    # Valid technique becomes a reusable card; the flag-bearing one is refused.
    stored = {item["title"]: item for item in result["techniques"]}
    assert stored["Classical shift cipher brute force"]["stored"] is True
    assert stored["Bad card"]["stored"] is False
    knowledge = Path("writeups/KNOWLEDGE.md").read_text()
    assert "Classical shift cipher brute force" in knowledge and "[出典](ksnctf/2-easy-cipher.md)" in knowledge
    assert ANSWER not in knowledge
    readme = Path("writeups/ksnctf/README.md").read_text()
    assert "1 / 2 問解決、50 点" in readme and "[WriteUP](2-easy-cipher.md)" in readme
    assert "| 23 | Villager B | pwn | 450 | 未着手 | - |" in readme
    assert "[ksnctf](ksnctf/README.md)" in Path("writeups/README.md").read_text()
    assert book.missing(contest_id)["solved_without_writeup"] == []


def test_save_keeps_evaluation_split_in_sync(solved):
    from metis.core.answer_vault import build_split

    database, contest_id, _run_id = solved
    book = WriteupBook(database)
    result = book.save(contest_id, "2", _entry())
    split_path = Path(result["evaluation_split"])
    assert split_path == Path("writeups/EVALUATION_SPLIT.json")
    recorded = json.loads(split_path.read_text(encoding="utf-8"))
    # save() must not leave EVALUATION_SPLIT.json stale: it equals a fresh rebuild.
    assert recorded == build_split(Path("writeups"))
    assert {"ctf": "ksnctf", "problem": "2", "writeup": "ksnctf/2-easy-cipher.md"} in recorded["practice"]


def test_unsolved_writeup_and_script_scope(solved):
    database, contest_id, _ = solved
    book = WriteupBook(database)
    progress = book.save(contest_id, "23", WriteupInput(summary="PIE有効のpwn。リモート検証待ち。"))
    assert "| 状態 | 未着手 |" in Path(progress["path"]).read_text()
    with pytest.raises(ValueError, match="scripts must be files"):
        book.save(contest_id, "23", WriteupInput(summary="スクリプト範囲の確認", scripts=["/etc/hosts"]))


def test_cli_writeup_save(solved, monkeypatch, capsys):
    database, contest_id, _ = solved
    payload = Path("entry.json")
    payload.write_text(json.dumps({"summary": "CLIからの保存テストです。", "flag": ANSWER}))
    monkeypatch.setattr(sys, "argv", ["metis", "writeup", "--database", str(database), "save", contest_id, "2",
                                      "--file", str(payload)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["path"].endswith("2-easy-cipher.md")
    monkeypatch.setattr(sys, "argv", ["metis", "writeup", "--database", str(database), "missing", contest_id])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["solved_without_writeup"] == []


def test_flag_is_checked_against_official_correct_submission(solved):
    import hmac as hmac_module
    import sqlite3
    database, contest_id, run_id = solved
    salt = "11" * 32
    WriteupBook(database)  # ensure tables
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS web_runs (run_id TEXT PRIMARY KEY, config TEXT NOT NULL, "
                   "state TEXT NOT NULL, forms TEXT NOT NULL, links TEXT NOT NULL, salt TEXT NOT NULL, "
                   "paused_until REAL NOT NULL DEFAULT 0)")
        db.execute("CREATE TABLE IF NOT EXISTS web_attempts (run_id TEXT NOT NULL, digest TEXT NOT NULL, "
                   "verdict TEXT NOT NULL, created REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 1, "
                   "PRIMARY KEY(run_id, digest))")
        db.execute("INSERT INTO web_runs VALUES (?,?,?,?,?,?,0)",
                   (run_id, json.dumps({"page_url": "https://ksnctf.sweetduet.info/problem/2"}), "{}", "[]", "[]", salt))
        digest = hmac_module.new(bytes.fromhex(salt), ANSWER.encode(), hashlib.sha256).hexdigest()
        db.execute("INSERT INTO web_attempts VALUES (?,?,?,?,1)", (run_id, digest, "correct", 1.0))
    book = WriteupBook(database)
    good = book.save(contest_id, "2", WriteupInput(summary="照合テスト（正しいflag）", flag=ANSWER))
    assert good["flag_check"] == "match"
    assert "| Flag照合 | 公式判定で正解した文字列と一致 |" in Path(good["path"]).read_text()
    bad = book.save(contest_id, "2", WriteupInput(summary="照合テスト（誤ったflag）", flag="FLAG_wrong"))
    assert bad["flag_check"] == "mismatch"
    assert book.save(contest_id, "23", WriteupInput(summary="未解決問題でのflag照合テスト", flag="FLAG_x"))["flag_check"] \
        == "unverifiable"


def test_slug_ids_are_not_duplicated_in_file_names(solved):
    database, contest_id, _ = solved
    board = ContestBoard(database)
    board.add(contest_id, [{"challenge_id": "base-16-32-64", "title": "base 16-32-64"}])
    book = WriteupBook(database)
    first = book.save(contest_id, "base-16-32-64", WriteupInput(summary="スラッグ形式のIDの確認です。"))
    assert Path(first["path"]).name == "base-16-32-64.md"
    import sqlite3
    old = Path(first["path"]).with_name("base-16-32-6-base-16-32-64.md")
    Path(first["path"]).rename(old)
    with sqlite3.connect(database) as db:  # simulate a write-up saved under the old naming
        db.execute("UPDATE ctf_writeups SET path=? WHERE challenge_id='base-16-32-64'", (str(old),))
    again = book.save(contest_id, "base-16-32-64", WriteupInput(summary="再保存で名前が揃うことの確認。"))
    assert Path(again["path"]).exists() and not old.exists()
