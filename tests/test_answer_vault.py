"""Answer vault (Issue #15): answers leave write-ups without being lost."""
import json
import stat
import subprocess
from pathlib import Path

import pytest

from metis.core.answer_vault import (
    ANSWER,
    EXAMPLE,
    AnswerVault,
    is_answer,
    migrate,
    redact,
    restore,
)

REPOSITORY = Path(__file__).resolve().parent.parent


def test_redact_replaces_answers_and_keeps_format_examples():
    text = "Flag: FLAG_abcDEF123\nformat FLAG_XXXXXXXX or Alpaca{...}; again FLAG_abcDEF123 and Alpaca{real_one}"
    updated, entries = redact(text, "ctf/1.md")
    assert "FLAG_abcDEF123" not in updated and "Alpaca{real_one}" not in updated
    assert "FLAG_XXXXXXXX" in updated and "Alpaca{...}" in updated
    assert updated.count("⟦answer:ctf/1.md#1⟧") == 2  # the same value gets one key
    assert {entry["value"] for entry in entries.values()} == {"FLAG_abcDEF123", "Alpaca{real_one}"}
    assert entries["ctf/1.md#1"]["line"] == 1
    assert is_answer("FLAG_abcDEF123") and not is_answer("FLAG_XXXXXXXX")


def test_vault_is_private_verified_and_never_overwrites(tmp_path):
    vault = AnswerVault(tmp_path / "v" / "answers.json")
    vault.put_many({"k#1": {"value": "FLAG_one111"}})
    vault.put_many({"k#1": {"value": "FLAG_two222"}})
    data = vault.load()
    assert data["k#1"]["value"] == "FLAG_one111" and data["k#1"]["alternates"] == ["FLAG_two222"]
    assert stat.S_IMODE(vault.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault.path.parent.stat().st_mode) == 0o700


def test_migrate_is_a_dry_run_until_applied_and_restore_is_exact(tmp_path):
    root = tmp_path / "writeups" / "ctf"
    (root / "files").mkdir(parents=True)
    original = {"1-a.md": "# A\n| Flag | `FLAG_firstAnswer1` |\nSolve gave FLAG_firstAnswer1.\n",
                "files/solve.py": "print('Alpaca{second_answer}')\n",
                "files/auth.txt": "Authorization: Basic cTg6RkxBR19maXJzdEFuc3dlcjE=\nhex 464c41475f6669727374416e7377657231\n",
                "2-b.md": "No answer, format is FLAG_XXXXXXXX.\n"}
    for name, text in original.items():
        (root / name).write_text(text)
    vault = AnswerVault(tmp_path / "vault.json")
    dry = migrate([tmp_path / "writeups"], tmp_path, vault)
    assert dry["answers"] == 4 and not dry["applied"] and not vault.path.exists()  # 2 answers + 2 encodings
    assert (root / "1-a.md").read_text() == original["1-a.md"]
    done = migrate([tmp_path / "writeups"], tmp_path, vault, apply=True)
    assert done["applied"] and sorted({item["file"] for item in done["files"]}) == [
        "writeups/ctf/1-a.md", "writeups/ctf/files/auth.txt", "writeups/ctf/files/solve.py"]
    auth = (root / "files/auth.txt").read_text()
    assert "RkxBR19maXJzdEFuc3dlcjE" not in auth and "464c41475f" not in auth
    assert "FLAG_firstAnswer1" not in (root / "1-a.md").read_text()
    assert "⟦answer:writeups/ctf/files/solve.py#1⟧" in (root / "files/solve.py").read_text()
    assert migrate([tmp_path / "writeups"], tmp_path, vault)["answers"] == 0  # idempotent
    back = restore([tmp_path / "writeups"], vault, apply=True)
    assert back["missing"] == []
    assert {name: (root / name).read_text() for name in original} == original


def test_migration_stops_before_touching_files_when_the_vault_cannot_be_written(tmp_path, monkeypatch):
    target = tmp_path / "w.md"
    target.write_text("FLAG_keepThisOne\n")
    vault = AnswerVault(tmp_path / "vault.json")

    def broken(_entries):
        raise RuntimeError("answer vault verification failed")

    monkeypatch.setattr(vault, "put_many", broken)
    with pytest.raises(RuntimeError):
        migrate([target], tmp_path, vault, apply=True)
    assert target.read_text() == "FLAG_keepThisOne\n"


def test_cli_dry_run_and_apply(tmp_path, monkeypatch, capsys):
    from metis.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "writeups").mkdir()
    (tmp_path / "writeups" / "x.md").write_text("FLAG_cliAnswer01\n")
    monkeypatch.setattr("sys.argv", ["metis", "writeup", "vault-migrate", "--vault", str(tmp_path / "v.json")])
    assert main() == 0 and json.loads(capsys.readouterr().out)["answers"] == 1
    monkeypatch.setattr("sys.argv", ["metis", "writeup", "vault-migrate", "--vault", str(tmp_path / "v.json"),
                                     "--apply"])
    assert main() == 0 and "FLAG_cliAnswer01" not in (tmp_path / "writeups" / "x.md").read_text()


def test_repository_tracks_no_answers():
    """Guard for Issue #15: tracked write-ups, work files and docs contain vault references only."""
    listed = subprocess.run(["git", "ls-files", "writeups", "work_nd", "docs", "challenges"], cwd=REPOSITORY,
                            capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    offenders = {}
    for name in listed.stdout.split():
        try:
            text = (REPOSITORY / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [m.group(0) for m in ANSWER.finditer(text) if not EXAMPLE.fullmatch(m.group(0))]
        if hits:
            offenders[name] = len(hits)  # counts only; values are never printed
    assert offenders == {}, f"answers found in tracked files (run `metis writeup vault-migrate`): {offenders}"


def test_munin_cards_record_the_basis_of_their_outcome(tmp_path):
    import hashlib

    from metis.core.codex_session import CodexSession
    from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard

    database = tmp_path / "state" / "metis.sqlite"
    artifact = tmp_path / "c.txt"
    artifact.write_text("Uryyb")
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="rot13", paths=[artifact],
                            commitment=hashlib.sha256(b"FLAG_basisTest01").hexdigest())["run_id"]
    assert session.submit(run_id, "FLAG_basisTest01")["verified"] is True
    knowledge = KnowledgeBase(database)
    stored = knowledge.remember(TechniqueCard(title="Rotation cipher", category="crypto",
                                              summary="Letters shifted by thirteen decode with rot13.",
                                              conditions="Alphabetic text with English letter frequencies.",
                                              outcome="success", source_run_id=run_id, source_split="practice"))
    card = knowledge.search("Rotation", limit=1)[0]["card"]
    assert stored["stored"] and "official verdict: correct" in card["evidence"]
    with pytest.raises(ValueError):
        knowledge.remember(TechniqueCard(title="Leaky", category="crypto", summary="Works for many inputs here.",
                                         conditions="Any text input.", outcome="success", source_run_id=run_id,
                                         evidence="the answer was FLAG_basisTest01"))


def test_problems_with_write_ups_are_practice_not_heldout(tmp_path):
    from metis.core.answer_vault import build_split, split_for, write_split

    (tmp_path / "ksnctf").mkdir()
    (tmp_path / "ksnctf" / "8-basic-is-secure.md").write_text("# x\n")
    (tmp_path / "ksnctf" / "README.md").write_text("index\n")
    assert [item["problem"] for item in build_split(tmp_path)["practice"]] == ["8"]
    write_split(tmp_path)
    assert split_for(tmp_path, "ksnctf", 8)["split"] == "practice"
    assert split_for(tmp_path, "ksnctf", 8)["independent_evaluation"] is False
    assert split_for(tmp_path, "ksnctf", 9)["split"] == "unlisted"
    assert split_for(tmp_path, "html", None)["split"] == "unlisted"


def test_repository_split_lists_every_write_up():
    import json as _json

    from metis.core.answer_vault import build_split

    recorded = _json.loads((REPOSITORY / "writeups" / "EVALUATION_SPLIT.json").read_text(encoding="utf-8"))
    assert recorded["heldout"] == [] and recorded == build_split(REPOSITORY / "writeups")
