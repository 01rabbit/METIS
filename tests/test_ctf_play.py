import hashlib
import json
import sys

import pytest

from metis.cli import main
from metis.core import ctf_swarm
from metis.core.codex_session import CodexSession
from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_contest_ops import contest_info_report, contest_refresh
from metis.core.ctf_platforms import detect, validate_rules
from metis.play import build_prompt, plan
from metis.play import main as play_main


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path / ".metis-state" / "metis.sqlite"


def test_detect_platforms_and_rules():
    alpaca = detect("https://alpacahack.com/daily")
    assert alpaca["platform"] == "alpacahack" and alpaca["rules"]["submission"] == "browser"
    assert alpaca["rules"]["instance_limit"] == 1
    assert detect("https://ctf.example.org/challenges")["platform"] == "unknown"
    with pytest.raises(ValueError):
        detect("ftp://example.org")
    with pytest.raises(ValueError, match="submission"):
        validate_rules({"submission": "fax"})
    with pytest.raises(ValueError, match="unsupported"):
        validate_rules({"password": "x"})


def test_new_configure_refresh_keeps_progress(state, tmp_path):
    board = ContestBoard(state)
    created = board.new("https://alpacahack.com/daily", "AlpacaHack Daily")
    contest_id = created["contest_id"]
    assert created["platform"] == "alpacahack" and created["catalog"] == "agent"
    # A solved challenge must survive refreshes untouched.
    note = tmp_path / "n.txt"
    note.write_text("x")
    session = CodexSession(state)
    run_id = session.intake(title="a", description="d", paths=[note],
                            commitment=hashlib.sha256(b"FLAG_a").hexdigest())["run_id"]
    session.submit(run_id, "FLAG_a")
    board.add(contest_id, [{"challenge_id": "a", "title": "A", "points": 1}])
    board.update(contest_id, "a", {"run_id": run_id, "state": "solved", "official_verified": True})
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps([{"challenge_id": "a", "title": "A", "points": 2, "solves": 9},
                                   {"challenge_id": "b", "title": "B", "category": "pwn",
                                    "url": "https://alpacahack.com/daily/challenges/b"},
                                   {"challenge_id": "b", "title": "B again"}]))
    result = contest_refresh(state, contest_id, listing_file=listing)
    assert result["added"] == ["b"] and result["updated"] == ["a"]
    items = {item["challenge_id"]: item for item in board.board(contest_id)["challenges"]}
    assert items["a"]["state"] == "solved" and items["a"]["points"] == 2 and items["b"]["state"] == "queued"
    assert contest_refresh(state, contest_id, listing_file=listing)["added"] == []
    agent = contest_refresh(state, contest_id)
    assert agent["needs_listing"] and "--file" in agent["next"]
    configured = board.configure(contest_id, {"rules": {"ends_at": "2026-12-31"}})
    assert configured["rules"]["submission"] == "browser" and configured["rules"]["ends_at"] == "2026-12-31"
    info = contest_info_report(state, contest_id)
    assert info["last_refresh"] and any("期間終了後" in line for line in info["rules_text"])


def test_refresh_from_ctfd_api(state, monkeypatch):
    board = ContestBoard(state)
    contest_id = board.new("https://ctf.example.org", "Example")["contest_id"]
    board.configure(contest_id, {"catalog": "ctfd", "adapter": "ctfd", "platform": "ctfd"})
    seen = {}

    def catalog(self, url, *, adapter, token_env=None, cookie_env=None):
        seen.update(url=url, adapter=adapter)
        return {"challenges": [{"challenge_id": "7", "title": "Seven", "category": "web", "points": 100,
                                "url": url, "adapter": "ctfd"}]}

    monkeypatch.setattr("metis.core.ctf_web.WebWorkflow.catalog", catalog)
    assert contest_refresh(state, contest_id)["added"] == ["7"]
    assert seen == {"url": "https://ctf.example.org", "adapter": "ctfd"}


def test_legacy_board_is_inferred_from_challenge_urls(state):
    board = ContestBoard(state)
    contest_id = board.create({"name": "old board"})["contest_id"]
    board.add(contest_id, [{"challenge_id": "x", "title": "X", "url": "https://alpacahack.com/daily/challenges/x"}])
    meta = board.meta(contest_id)
    assert meta["configured"] is False and meta["platform"] == "alpacahack"
    assert meta["url"] == "https://alpacahack.com/daily"
    prompt = build_prompt(state, contest_id, new=False)
    assert "まだ保存されていない" in prompt and "contest configure" in prompt


def test_prompt_and_tmux_plan(state, tmp_path):
    contest_id = ContestBoard(state).new("https://alpacahack.com/daily", "Daily")["contest_id"]
    new_prompt = build_prompt(state, contest_id, new=True)
    assert "新しく登録した大会" in new_prompt and contest_id in new_prompt
    assert "ブラウザのフォーム" in new_prompt and f"refresh {contest_id} --file" in new_prompt
    continued = build_prompt(state, contest_id, new=False)
    assert "続き" in continued and "swarm handoff" in continued
    commands = plan(state, contest_id, root=tmp_path, prompt="PROMPT", workers=2, chrome=True)
    session = f"metis-{contest_id[:8]}"
    assert commands[0][:6] == ["tmux", "new-session", "-d", "-s", session, "-n"] and commands[0][6] == "claude"
    assert "claude --chrome PROMPT" in commands[0][-1]
    names = [command[command.index("-n") + 1] for command in commands if "-n" in command]
    assert names == ["claude", "dashboard", "swarm", "workers"]
    assert commands[-1] == ["tmux", "select-window", "-t", f"{session}:claude"]
    assert [command for command in plan(state, contest_id, root=tmp_path, prompt="P", workers=0, chrome=False)
            if "swarm" in command[-1] and " run " in command[-1]] == []


def test_play_print_prompt_and_cli(state, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metis", "contest", "--database", str(state), "new",
                                      "https://ksnctf.sweetduet.info/", "--name", "ksnctf"])
    assert main() == 0
    contest_id = json.loads(capsys.readouterr().out)["contest_id"]
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": __import__("io").BytesIO(
        json.dumps({"rules": {"writeup_publish": "anytime"}}).encode())})())
    monkeypatch.setattr(sys, "argv", ["metis", "contest", "--database", str(state), "configure", contest_id])
    assert main() == 0
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["metis", "contest", "--database", str(state), "info", contest_id])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["rules"]["writeup_publish"] == "anytime"
    assert play_main([contest_id, "--database", str(state), "--print-prompt"]) == 0
    assert "ksnctf" in capsys.readouterr().out


def test_swarm_tmux_joins_existing_play_session(state, monkeypatch, tmp_path):
    contest_id = ContestBoard(state).create({"name": "joined"})["contest_id"]
    issued = []
    monkeypatch.setattr(ctf_swarm.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(ctf_swarm, "tmux_windows", lambda session: ["claude", "dashboard"])
    monkeypatch.setattr(ctf_swarm.subprocess, "run", lambda command, check: issued.append(command))
    ctf_swarm.launch_tmux(state, contest_id, ["--workers", "1"], 1)
    assert issued[0][:3] == ["tmux", "new-window", "-d"] and all("new-session" not in command for command in issued)
    assert not any("watch" in " ".join(command) for command in issued)  # dashboard already there
    monkeypatch.setattr(ctf_swarm, "tmux_windows", lambda session: ["claude", "dashboard", "swarm"])
    with pytest.raises(ValueError, match="already running"):
        ctf_swarm.launch_tmux(state, contest_id, ["--workers", "1"], 1)
