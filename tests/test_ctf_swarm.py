import hashlib
import json
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from metis.core.codex_session import CodexSession
from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_swarm import Swarm, status

FAKE_AGENT = '''#!{python}
"""Stand-in for a headless agent CLI. Behaviour per challenge comes from FAKE_PLAN."""
import json, os, re, subprocess, sys, time
prompt = sys.argv[sys.argv.index("-p") + 1]
plan = json.loads(open(os.environ["FAKE_PLAN"]).read())
challenge = os.environ["METIS_CHALLENGE"]
with open(os.environ["FAKE_TRACE"], "a") as trace:
    trace.write(json.dumps({{"challenge": challenge, "start": time.time()}}) + "\\n")
time.sleep(1.0)
action = plan.get(challenge, "nothing")
metis = [sys.executable, "-m", "metis.cli"]
db = ["--database", os.environ["FAKE_DB"]]
if action.startswith("answer:"):
    run_id = re.search(r"既存の run: (\\w+)", prompt).group(1)
    subprocess.run(metis + ["codex", *db, "submit", run_id], input=action[7:].encode(), check=True,
                   capture_output=True)
elif action == "block":
    subprocess.run(metis + ["contest", *db, "release", os.environ["METIS_CONTEST"], challenge,
                            "--worker", os.environ["METIS_WORKER"], "--state", "blocked",
                            "--note", "service unreachable"], check=True, capture_output=True)
print("done")
'''


@pytest.fixture
def contest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = tmp_path / ".metis-state" / "metis.sqlite"
    session = CodexSession(database)
    board = ContestBoard(database)
    contest_id = board.create({"name": "Swarm test", "max_parallel": 2})["contest_id"]
    plan = {}
    items = []
    for index, kind in enumerate(["solve", "solve", "solve", "block", "stuck"], start=1):
        answer = f"FLAG_swarm_{index}"
        note = tmp_path / f"c{index}.txt"
        note.write_text(answer)
        run_id = session.intake(title=f"c{index}", description="d", paths=[note],
                                commitment=hashlib.sha256(answer.encode()).hexdigest())["run_id"]
        items.append({"challenge_id": str(index), "title": f"challenge {index}", "category": f"cat{index % 3}",
                      "points": 100 * index})
        plan[str(index)] = {"solve": "answer:" + answer, "block": "block", "stuck": "nothing"}[kind]
        board.add(contest_id, [items[-1]])
        board.update(contest_id, str(index), {"run_id": run_id})
    bindir = tmp_path / "bin"
    bindir.mkdir()
    agent = bindir / "claude"
    agent.write_text(FAKE_AGENT.format(python=sys.executable))
    agent.chmod(agent.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setenv("FAKE_PLAN", str(tmp_path / "plan.json"))
    monkeypatch.setenv("FAKE_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("FAKE_DB", str(database))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    return database, contest_id, str(agent)


def test_swarm_runs_workers_in_parallel_and_settles_from_evidence(contest, tmp_path):
    database, contest_id, agent = contest
    swarm = Swarm(database, contest_id, workers=3, minutes=5, max_sessions=1, executable=agent)
    started = time.monotonic()
    result = swarm.run()
    elapsed = time.monotonic() - started
    states = {item["challenge_id"]: item["state"] for item in ContestBoard(database).board(contest_id)["challenges"]}
    assert states == {"1": "solved", "2": "solved", "3": "solved", "4": "blocked", "5": "blocked"}
    assert result["solved"] == 3 and result["score"] == 600
    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert sorted(entry["challenge"] for entry in trace) == ["1", "2", "3", "4", "5"]  # each claimed once
    starts = sorted(entry["start"] for entry in trace)
    assert starts[2] - starts[0] < 1.0  # three sessions overlapped instead of running one after another
    assert elapsed < 30  # sanity bound; overlap above is the parallelism check
    notes = {item["challenge_id"]: item["notes"] for item in ContestBoard(database).board(contest_id)["challenges"]}
    assert notes["4"] == "service unreachable" and "sessions ended" in notes["5"]
    assert status(database, contest_id)["counts"]["solved"] == 3
    logs = list((database.parent / "swarm" / contest_id).glob("w*-*.log"))
    assert len(logs) == 5


def test_claims_are_exclusive_and_expired_leases_return(contest):
    database, contest_id, _ = contest
    board = ContestBoard(database)
    claimed: list[str | None] = []

    def grab(name):
        claimed.append(board.claim(contest_id, name, lease_seconds=60)["challenge"]["challenge_id"])

    with board_parallel(board, contest_id, 4):
        threads = [threading.Thread(target=grab, args=(f"w{index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert len(set(claimed)) == 4  # no challenge leased twice
    assert board.claim(contest_id, "w9", lease_seconds=60)["reason"] == "all parallel slots are leased"
    import sqlite3
    with sqlite3.connect(database) as db:
        db.execute("UPDATE ctf_contest_challenges SET lease_until=0 WHERE worker='w0'")
    rescued = board.claim(contest_id, "w9", lease_seconds=60)["challenge"]
    assert rescued is not None and rescued["worker"] == "w9"
    with pytest.raises(ValueError, match="another worker"):
        board.release(contest_id, rescued["challenge_id"], "w1", state="queued")


class board_parallel:
    def __init__(self, board, contest_id, value):
        import sqlite3
        self.sqlite3, self.board, self.contest_id, self.value = sqlite3, board, contest_id, value

    def __enter__(self):
        with self.sqlite3.connect(self.board.database) as db:
            db.execute("UPDATE ctf_contests SET max_parallel=? WHERE contest_id=?", (self.value, self.contest_id))

    def __exit__(self, *args):
        return False


def test_stop_file_prevents_new_claims(contest):
    database, contest_id, agent = contest
    swarm = Swarm(database, contest_id, workers=2, minutes=5, executable=agent)
    swarm.stop_file.touch()
    swarm.worker("w1")  # returns immediately without claiming
    assert all(item["state"] == "queued" for item in ContestBoard(database).board(contest_id)["challenges"])


def test_chrome_workers_preallow_browser_tools(contest):
    database, contest_id, agent = contest
    command = Swarm(database, contest_id, workers=1, minutes=5, chrome=True, executable=agent).command("x")
    assert "--chrome" in command and "mcp__claude-in-chrome" in command
    assert "mcp__claude-in-chrome" not in Swarm(database, contest_id, workers=1, minutes=5,
                                                 executable=agent).command("x")


def test_cli_options_after_contest_id_are_applied(contest, monkeypatch, capsys):
    database, contest_id, _ = contest
    captured = {}

    class FakeSwarm:
        def __init__(self, database, contest_id, **kwargs):
            captured.update(kwargs)
            self.logs = Path("logs")

        def run(self, once=False):
            return {"done": True}

    monkeypatch.setattr("metis.cli.Swarm", FakeSwarm)
    from metis.cli import main
    monkeypatch.setattr(sys, "argv", ["metis", "swarm", "--database", str(database), "run", contest_id,
                                      "--workers", "4", "--chrome", "--minutes", "30",
                                      "--agent-arg=--verbose"])
    assert main() == 0
    assert captured["workers"] == 4 and captured["chrome"] is True and captured["minutes"] == 30
    assert captured["agent_args"] == ["--verbose"]
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["metis", "contest", "--database", str(database), "list"])
    assert main() == 0
    listed = json.loads(capsys.readouterr().out)["contests"]
    assert listed[0]["contest_id"] == contest_id and listed[0]["challenges"] == 5


def test_candidate_file_avoids_shell_pipes(tmp_path, monkeypatch, capsys):
    import hashlib as hashlib_module

    from metis.cli import main
    database = tmp_path / "metis.sqlite"
    note = tmp_path / "n.txt"
    note.write_text("x")
    run_id = CodexSession(database).intake(title="t", description="d", paths=[note],
                                           commitment=hashlib_module.sha256(b"FLAG_file").hexdigest())["run_id"]
    from metis.cli import read_candidate
    candidate = tmp_path / "c.candidate"
    candidate.write_bytes(b"FLAG_file\n")
    assert read_candidate(candidate) == "FLAG_file"  # one trailing newline removed, nothing else
    candidate.write_bytes(b" FLAG_file \r\n")
    assert read_candidate(candidate) == " FLAG_file "
    assert run_id
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(database), "attest", run_id,
                                      "--verdict", "correct", "--evidence", "UI showed Correct",
                                      "--candidate-file", str(candidate)])
    with pytest.raises(SystemExit):
        main()  # an intake run has no web run: rejected with a reason, never an empty candidate
    assert "invalid bounded candidate" not in capsys.readouterr().err


def test_stream_json_is_rendered_readably():
    from metis.core.ctf_swarm import describe_line
    assert describe_line(b'{"type":"system","subtype":"init","model":"claude-x"}') == ["# session start (model claude-x)"]
    assistant = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "RSA with a shared prime;\nchecking gcd"},
        {"type": "tool_use", "name": "Bash", "input": {"command": ".venv/bin/metis codex context abc"}},
        {"type": "tool_use", "name": "mcp__claude-in-chrome__navigate", "input": {"url": "https://alpacahack.com/x"}}]}}
    assert describe_line(json.dumps(assistant).encode()) == [
        "> RSA with a shared prime; checking gcd", "$ .venv/bin/metis codex context abc",
        "browser navigate https://alpacahack.com/x"]
    error = {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                       "content": "Permission denied"}]}}
    assert describe_line(json.dumps(error).encode()) == ["! Permission denied"]
    done = {"type": "result", "subtype": "success", "duration_ms": 61000, "total_cost_usd": 0.4, "result": "solved"}
    assert describe_line(json.dumps(done).encode())[0].startswith("= finished (success, 61s, $0.40) solved")
    assert describe_line(b"plain codex output") == ["plain codex output"]


def test_dashboard_renders_state(contest):
    from metis.core.ctf_dashboard import render, snapshot
    database, contest_id, _ = contest
    board = ContestBoard(database)
    leased = board.claim(contest_id, "w1", lease_seconds=600)["challenge"]
    activity = database.parent / "swarm" / contest_id / "activity.json"
    activity.parent.mkdir(parents=True, exist_ok=True)
    activity.write_text(json.dumps({"w1": {"challenge": leased["challenge_id"], "started": time.time() - 65,
                                           "last": "$ .venv/bin/metis sandbox run x", "time": time.time()}}))
    lines = render(snapshot(database, contest_id), width=160)
    text = "\n".join(line for line, _ in lines)
    assert "solved 0/5" in text and "working 1" in text
    assert "w1" in text and "1:0" in text and "metis sandbox run" in text
    styles = {line.split()[1]: style for line, style in lines if line.startswith("  >> ")}
    assert styles[leased["challenge_id"]] == "active"


def test_tmux_plan_layout(tmp_path):
    from metis.core.ctf_swarm import tmux_plan
    session, commands = tmux_plan(tmp_path / ".metis-state" / "metis.sqlite", "0e5c5caaff2e", ["--workers", "6"], 6,
                                  root=tmp_path)
    assert session == "metis-0e5c5caa"
    windows = [command[command.index("-n") + 1] for command in commands if "-n" in command]
    assert windows == ["swarm", "dashboard", "workers", "workers2"]
    tails = [command[-1] for command in commands if command[1] in {"new-window", "split-window"} and "tail" in command[-1]]
    assert len(tails) == 6 and "w6.log" in tails[-1]
    assert "--workers 6" in commands[0][-1] and commands[-1][-1].endswith(":dashboard")


def test_handoff_state_and_prompt(contest, monkeypatch, capsys):
    database, contest_id, _ = contest
    board = ContestBoard(database)
    claimed = board.claim(contest_id, "w1")["challenge"]["challenge_id"]
    board.release(contest_id, claimed, "w1", state="handoff", note="送る値は INT_MIN と -1。インスタンス起動が必要")
    assert board.claim(contest_id, "w2")["challenge"]["challenge_id"] != claimed  # not re-queued
    from metis.cli import main
    from metis.core.ctf_dashboard import render, snapshot
    from metis.core.ctf_swarm import handoff
    report = handoff(database, contest_id)
    assert report["count"] == 1 and report["challenges"][0]["challenge_id"] == claimed
    assert "INT_MIN" in report["prompt"] and "--replace" in report["prompt"]
    text = "\n".join(line for line, _ in render(snapshot(database, contest_id)))
    assert "HO " in text and "swarm handoff" in text
    monkeypatch.setattr(sys, "argv", ["metis", "swarm", "--database", str(database), "handoff", contest_id, "--prompt"])
    assert main() == 0
    assert "引き継いだ問題が 1 問" in capsys.readouterr().out
