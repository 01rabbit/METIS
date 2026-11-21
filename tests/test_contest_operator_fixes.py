import json
import subprocess
import sys
from pathlib import Path

from metis.core.ctf_contest import ContestBoard

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "challenges/training/fixture-001.json"


def cli(*args, stdin=None):
    return subprocess.run([sys.executable, "-m", "metis.cli", *map(str, args)], input=stdin,
                          check=False, capture_output=True, text=True)


def _contest_with_challenge(database):
    created = json.loads(cli("contest", "--database", database, "create",
                             stdin=json.dumps({"name": "Cup", "format": "jeopardy"})).stdout)
    cli("contest", "--database", database, "add", created["contest_id"],
        stdin=json.dumps([{"challenge_id": "c1", "title": "C1", "category": "web"}]))
    return created["contest_id"]


def test_claim_takes_challenges_marked_investigating_by_dispatch(tmp_path):
    board = ContestBoard(tmp_path / "metis.sqlite")
    contest_id = board.create({"name": "Mixed", "format": "jeopardy", "max_parallel": 2})["contest_id"]
    board.add(contest_id, [
        {"challenge_id": "a", "title": "A", "category": "web", "points": 100},
        {"challenge_id": "b", "title": "B", "category": "crypto", "points": 100},
    ])
    dispatched = {item["challenge_id"] for item in board.dispatch(contest_id)["active"]}
    assert dispatched == {"a", "b"}
    first = board.claim(contest_id, "w1")
    assert first["challenge"] is not None and first["challenge"]["worker"] == "w1"
    second = board.claim(contest_id, "w2")
    assert second["challenge"]["challenge_id"] != first["challenge"]["challenge_id"]
    assert board.claim(contest_id, "w3")["challenge"] is None


def test_contest_update_and_plan_explain_where_run_ids_come_from(tmp_path):
    database = tmp_path / "runs.sqlite"
    prepared = json.loads(cli("prepare", FIXTURE, "--database", database).stdout)
    contest_id = _contest_with_challenge(database)
    result = cli("contest", "--database", database, "update", contest_id, "c1",
                 stdin=json.dumps({"run_id": prepared["run_id"]}))
    assert result.returncode == 2
    assert "metis codex intake" in result.stderr and "metis web open" in result.stderr
    plan = cli("plan", prepared["run_id"], "--database", database)
    assert plan.returncode == 2 and "metis codex intake" in plan.stderr


def test_memory_learn_reports_specific_safe_reason_for_unlisted_run(tmp_path):
    database = tmp_path / "runs.sqlite"
    intake = cli("codex", "--database", database, "intake", "--title", "Unlisted task")
    assert intake.returncode == 0, intake.stderr
    run_id = json.loads(intake.stdout)["run_id"]
    card = {"title": "Decode layered text", "category": "misc", "summary": "Layered encodings decode in order.",
            "conditions": "Visible encoded text", "outcome": "inconclusive", "source_run_id": run_id}
    result = cli("memory", "--database", database, "learn", stdin=json.dumps(card))
    assert result.returncode == 2
    assert "unlisted source runs cannot enter reusable memory" in result.stderr


def test_writeup_save_warns_when_techniques_are_not_stored(tmp_path):
    database = tmp_path / "runs.sqlite"
    contest_id = _contest_with_challenge(database)
    entry = {"summary": "Solved by reading the page source carefully.",
             "techniques": [{"title": "Read page source", "category": "web",
                             "summary": "Inspect the page source for hints.", "conditions": "Public page"}]}
    result = cli("writeup", "--database", database, "--root", tmp_path / "w", "save", contest_id, "c1",
                 stdin=json.dumps(entry))
    assert result.returncode == 0, result.stderr
    assert "NOT stored" in json.loads(result.stdout)["warning"]
    assert "warning:" in result.stderr


def test_sequential_plan_includes_delegation_hint(tmp_path):
    database = tmp_path / "runs.sqlite"
    intake = cli("codex", "--database", database, "intake", "--title", "Simple task")
    run_id = json.loads(intake.stdout)["run_id"]
    result = cli("plan", run_id, "--database", database, "--mode", "sequential")
    assert result.returncode == 0, result.stderr
    assert "--mode delegated --reason" in json.loads(result.stdout)["next"]
