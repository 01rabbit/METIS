"""Run N independent agent workers against one contest board in parallel.

Each worker loops: lease the best queued challenge (`ContestBoard.claim`), start a
fresh headless agent session for that one challenge, renew the lease while the
session runs, then settle the board from METIS evidence:

* linked run officially solved            -> ``solved``
* the agent released it as blocked/...     -> left as the agent set it
* otherwise, after ``max_sessions`` tries  -> ``blocked`` (else back to ``queued``)

One challenge per session keeps every agent's context small, so a long contest
never degrades into one huge, slow conversation. Logs go to
``.metis-state/swarm/<contest>/``; creating the file ``STOP`` there makes every
worker finish its current challenge and exit.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from metis.core.codex_session import CodexSession
from metis.core.ctf_contest import ContestBoard

AGENTS = ("claude", "codex")
CLAUDE_TOOLS = ["Bash(.venv/bin/metis:*)", "Bash(./.venv/bin/metis:*)", "Read", "Write", "Edit", "Grep",
                "Glob", "Agent"]

PROMPT = """あなたは METIS スウォームのワーカー {worker} です。担当は次の1問だけです。
他の問題には触れず、大会キュー全体の操作（claim / dispatch）もしないでください。

- 大会: {contest_name}（contest_id: {contest_id}）
- 問題: {challenge_id} — {title}（カテゴリ: {category}、配点: {points:g}）
- 問題の場所: {location}
- 既存の run: {run_id}
- 前回までのメモ: {notes}
- 持ち時間: 約 {minutes} 分（超えるとこのセッションは終了されます）

手順（AGENTS.md と .agents/skills/metis/SKILL.md の規則に従うこと）:
1. 既存の run があればそれを使う（`.venv/bin/metis web context RUN_ID`）。無ければ問題を開き、
   `printf '%s' '{{"run_id": "RUN_ID"}}' | .venv/bin/metis contest update {contest_id} {challenge_id}` で紐付ける。
   同じ問題を開き直さないこと。期限切れの run は `metis codex extend` で再開する。
2. 解析する。必要なら ctf-* サブエージェントに並列で分担させてよい。問題プログラムは
   `.venv/bin/metis sandbox ...` の中だけで動かす（パイプ・リダイレクト・cd を付けず単独で実行）。
3. この問題に限り、根拠のある flag 候補を自分で公式に提出してよい。1候補1回。
   候補は Write ツールで `.metis-state/work/{challenge_id}.candidate` に書き、パイプを使わずに
   `.venv/bin/metis web submit RUN_ID --candidate-file .metis-state/work/{challenge_id}.candidate` で提出する。
   ブラウザ提出のサイト（`metis web context` の submission_mode が browser）は、画面のフォームで提出して結果を確認し、
   `.venv/bin/metis web attest RUN_ID --verdict correct|incorrect --evidence '画面の表示' --candidate-file 同じファイル`
   で記録する。
4. 正解したら、すぐに `metis writeup save {contest_id} {challenge_id} --file ...` で WriteUP を保存する。
5. 解法は分かったが、最後の一歩にサインイン済みブラウザが要る（問題インスタンスの起動、ログイン、
   ブラウザでしか取れない配布物など）場合は、操作者に引き継ぐ。ソース解析・ペイロード作成・検証できる部分は
   先に済ませ、解法・送る値・ソルバーのパスを WriteUP（`metis writeup save`、flag なし）に詳しく書き、
   `.venv/bin/metis contest release {contest_id} {challenge_id} --worker {worker} --state handoff --note '要点'`
   を実行して終了する（note は 500 文字以内で、何を送れば解けるかを書く）。
6. 到達不能・持ち時間内に進展しないなど、解法の見通しが立たない場合は、試したことを短い WriteUP に残し、
   `.venv/bin/metis contest release {contest_id} {challenge_id} --worker {worker} --state blocked --note '理由'`
   を実行して終了する。
7. ユーザーへの質問はしない（無人実行）。判断できない操作は行わず、handoff か blocked で終える。
最後に1行で結果（solved / handoff / blocked / 継続が必要）を出力して終了すること。
"""


def _short(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _tool(name: str, data: dict[str, Any]) -> str:
    if name == "Bash":
        return "$ " + _short(data.get("command", ""))
    if name in {"Read", "Write", "Edit"}:
        return f"{name.lower()} {_short(data.get('file_path', ''), 100)}"
    if name in {"Grep", "Glob"}:
        return f"{name.lower()} {_short(data.get('pattern', ''), 100)}"
    if name == "Agent":
        return "subagent " + _short(data.get("subagent_type", "") + ": " + str(data.get("description", "")), 120)
    if name.startswith("mcp__claude-in-chrome__"):
        action = name.rsplit("__", 1)[-1]
        detail = data.get("url") or data.get("action") or data.get("text") or ""
        return f"browser {action} {_short(detail, 100)}"
    return f"{name} {_short(json.dumps(data, ensure_ascii=False), 100)}"


def describe_line(line: bytes) -> list[str]:
    """Readable summary of one agent output line (Claude stream-json, or plain text)."""
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        event = json.loads(text)
    except ValueError:
        return [_short(text, 200)]
    if not isinstance(event, dict):
        return [_short(text, 200)]
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return [f"# session start (model {event.get('model', '?')})"]
    if kind == "assistant":
        output = []
        for item in (event.get("message") or {}).get("content") or []:
            if item.get("type") == "text" and item.get("text", "").strip():
                output.append("> " + _short(item["text"], 200))
            elif item.get("type") == "tool_use":
                output.append(_tool(str(item.get("name", "?")), item.get("input") or {}))
        return output
    if kind == "user":
        output = []
        for item in (event.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("is_error"):
                content = item.get("content")
                if isinstance(content, list):
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                output.append("! " + _short(content or "tool error", 160))
        return output
    if kind == "result":
        cost = event.get("total_cost_usd")
        seconds = (event.get("duration_ms") or 0) / 1000
        return [f"= finished ({event.get('subtype', '?')}, {seconds:.0f}s"
                + (f", ${cost:.2f}" if isinstance(cost, (int, float)) else "") + ") "
                + _short(event.get("result", ""), 160)]
    return []


def _now() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


class Swarm:
    def __init__(self, database: Path, contest_id: str, *, workers: int = 8, agent: str = "claude",
                 minutes: int = 40, max_sessions: int = 2, chrome: bool = False, model: str | None = None,
                 agent_args: list[str] | None = None, root: Path | None = None, executable: str | None = None):
        if agent not in AGENTS:
            raise ValueError("agent must be claude or codex")
        if not 1 <= workers <= 16 or not 5 <= minutes <= 240 or not 1 <= max_sessions <= 5:
            raise ValueError("workers 1-16, minutes 5-240, max_sessions 1-5")
        self.database = database
        self.board = ContestBoard(database)
        self.contest = self.board._contest(contest_id)
        self.contest_id = contest_id
        self.workers, self.agent, self.minutes, self.max_sessions = workers, agent, minutes, max_sessions
        self.chrome, self.model, self.agent_args = chrome, model, list(agent_args or [])
        self.root = (root or Path.cwd()).resolve()
        self.executable = executable or shutil.which(agent)
        if self.executable is None:
            raise ValueError(f"{agent} CLI not found on PATH")
        self.logs = database.parent / "swarm" / contest_id
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.events: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        # Never exceed the board's own parallel limit.
        if self.contest["max_parallel"] < workers:
            with sqlite3.connect(database, timeout=30) as db:
                db.execute("UPDATE ctf_contests SET max_parallel=? WHERE contest_id=?", (workers, contest_id))

    @property
    def stop_file(self) -> Path:
        return self.logs / "STOP"

    def _record(self, **entry: Any) -> None:
        entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.events.append(entry)
            with (self.logs / "events.jsonl").open("a") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def prompt(self, worker: str, challenge: dict[str, Any]) -> str:
        if challenge.get("url"):
            location = challenge["url"]
            if challenge.get("adapter") in {"ctfd", "rctf"}:
                location += f"（`metis web open {challenge['url']} --adapter {challenge['adapter']} " \
                            f"--challenge-id {challenge['challenge_id']}`）"
        else:
            location = "不明（大会の問題一覧から探す）"
        return PROMPT.format(worker=worker, contest_name=self.contest["name"], contest_id=self.contest_id,
                             challenge_id=challenge["challenge_id"], title=challenge["title"],
                             category=challenge["category"], points=challenge["points"], location=location,
                             run_id=challenge.get("run_id") or "なし", notes=challenge.get("notes") or "なし",
                             minutes=self.minutes)

    def command(self, prompt: str) -> list[str]:
        assert self.executable is not None
        if self.agent == "claude":
            command = [self.executable, "-p", prompt, "--output-format", "stream-json", "--verbose",
                       "--allowedTools", *CLAUDE_TOOLS]
            if self.chrome:
                # Headless workers cannot answer permission prompts, so the browser tools
                # must be pre-allowed; site scope stays with the extension's own settings.
                command[command.index("--allowedTools") + 1:command.index("--allowedTools") + 1] = [
                    "mcp__claude-in-chrome"]
                command.append("--chrome")
            if self.model:
                command += ["--model", self.model]
        else:
            command = [self.executable, "exec", *(["--model", self.model] if self.model else []), prompt]
        return command + self.agent_args

    def _activity(self, worker: str, **entry: Any) -> None:
        """Latest action per worker, for `metis swarm watch` in another process."""
        with self.lock:
            path = self.logs / "activity.json"
            try:
                data = json.loads(path.read_text()) if path.exists() else {}
            except ValueError:
                data = {}
            data[worker] = {**data.get(worker, {}), **entry, "time": time.time()}
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False))
            temporary.replace(path)

    def _pump(self, worker: str, challenge_id: str, stream: Any, log: Path) -> None:
        """Turn the agent's event stream into readable lines (per-challenge and per-worker logs)."""
        raw = log.with_suffix(".jsonl")
        worker_log = self.logs / f"{worker}.log"
        last_write = 0.0
        with raw.open("ab") as raw_out, log.open("a", encoding="utf-8") as text_out, \
                worker_log.open("a", encoding="utf-8") as worker_out:
            header = f"=== {time.strftime('%H:%M:%S')} {worker} -> {challenge_id} ===\n"
            text_out.write(header)
            worker_out.write(header)
            for line in iter(stream.readline, b""):
                raw_out.write(line)
                lines = describe_line(line)
                for item in lines:
                    stamped = f"{time.strftime('%H:%M:%S')} {item}\n"
                    text_out.write(stamped)
                    worker_out.write(stamped)
                text_out.flush()
                worker_out.flush()
                if lines and time.monotonic() - last_write > 1:
                    self._activity(worker, challenge=challenge_id, last=lines[-1][:160])
                    last_write = time.monotonic()

    def _session(self, worker: str, challenge: dict[str, Any]) -> int | None:
        challenge_id = challenge["challenge_id"]
        safe = re.sub(r"[^\w.-]", "_", challenge_id)
        log = self.logs / f"{worker}-{safe}-{_now()}.log"
        environment = dict(os.environ, METIS_WORKER=worker, METIS_CONTEST=self.contest_id,
                           METIS_CHALLENGE=challenge_id)
        self._activity(worker, challenge=challenge_id, title=challenge["title"], started=time.time(),
                       last="session starting", log=log.name)
        process = subprocess.Popen(self.command(self.prompt(worker, challenge)), cwd=self.root,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=environment, start_new_session=True)
        assert process.stdout is not None
        pump = threading.Thread(target=self._pump, args=(worker, challenge_id, process.stdout, log), daemon=True)
        pump.start()
        deadline = time.monotonic() + self.minutes * 60
        last_beat = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    self._record(worker=worker, challenge=challenge_id, event="timeout", log=log.name)
                    return None
                if time.monotonic() - last_beat > 300:
                    try:
                        self.board.heartbeat(self.contest_id, challenge_id, worker,
                                             lease_seconds=self.minutes * 60 + 600)
                    except ValueError:
                        pass  # The agent already released the challenge itself.
                    last_beat = time.monotonic()
                time.sleep(2)
            return process.returncode
        finally:
            pump.join(timeout=10)
            self._activity(worker, last=f"session ended ({process.returncode})")

    def settle(self, worker: str, challenge_id: str) -> str:
        current = self.board._challenge(self.contest_id, challenge_id)
        if current["state"] != "investigating" or current["worker"] != worker:
            return current["state"]  # The agent released it (blocked/abandoned) or it was settled.
        run_id = current.get("run_id")
        if run_id:
            try:
                if CodexSession(self.database).context(run_id)["status"] == "solved":
                    return self.board.release(self.contest_id, challenge_id, worker, state="solved")["state"]
            except (ValueError, IndexError):
                pass
        if current["sessions"] >= self.max_sessions:
            note = f"{current['sessions']} sessions ended without an official verdict"
            return self.board.release(self.contest_id, challenge_id, worker, state="blocked", note=note)["state"]
        return self.board.release(self.contest_id, challenge_id, worker, state="queued")["state"]

    def worker(self, worker: str, once: bool = False) -> None:
        while not self.stop_file.exists():
            claim = self.board.claim(self.contest_id, worker, lease_seconds=self.minutes * 60 + 600)
            challenge = claim["challenge"]
            if challenge is None:
                if claim["reason"] == "queue empty" and claim["active"] == 0:
                    self._record(worker=worker, event="queue empty; stopping")
                    return
                time.sleep(3 if claim["reason"] == "queue empty" else 15)
                continue
            self._record(worker=worker, challenge=challenge["challenge_id"], event="claimed",
                         title=challenge["title"])
            code = self._session(worker, challenge)
            state = self.settle(worker, challenge["challenge_id"])
            self._record(worker=worker, challenge=challenge["challenge_id"], event="settled", state=state,
                         exit_code=code)
            if once:
                return

    def run(self, once: bool = False) -> dict[str, Any]:
        if self.stop_file.exists():
            self.stop_file.unlink()
        threads = [threading.Thread(target=self.worker, args=(f"w{index + 1}", once), daemon=True)
                   for index in range(self.workers)]
        for index, thread in enumerate(threads):
            thread.start()
            time.sleep(0.3 if index else 0)  # Stagger starts slightly to avoid a thundering herd.
        for thread in threads:
            thread.join()
        board = self.board.board(self.contest_id)
        return {"contest_id": self.contest_id, "workers": self.workers,
                "solved": sum(item["state"] == "solved" for item in board["challenges"]),
                "handoff": sum(item["state"] == "handoff" for item in board["challenges"]),
                "blocked": sum(item["state"] == "blocked" for item in board["challenges"]),
                "queued": sum(item["state"] == "queued" for item in board["challenges"]),
                "score": board["score"], "events": len(self.events), "logs": str(self.logs)}


def status(database: Path, contest_id: str) -> dict[str, Any]:
    board = ContestBoard(database).board(contest_id)
    now = time.time()
    active = [{"worker": item["worker"], "challenge_id": item["challenge_id"], "title": item["title"],
               "lease_remaining": round((item["lease_until"] or now) - now), "sessions": item["sessions"]}
              for item in board["challenges"] if item["state"] == "investigating" and item["worker"]]
    counts = {state: sum(item["state"] == state for item in board["challenges"])
              for state in ("queued", "investigating", "solved", "handoff", "blocked", "abandoned")}
    logs = database.parent / "swarm" / contest_id
    recent = []
    events = logs / "events.jsonl"
    if events.exists():
        recent = [json.loads(line) for line in events.read_text().splitlines()[-15:]]
    return {"contest_id": contest_id, "score": board["score"], "counts": counts, "active": active,
            "stop_requested": (logs / "STOP").exists(), "recent_events": recent}


def session_name(contest_id: str) -> str:
    return f"metis-{contest_id[:8]}"


def swarm_windows(database: Path, contest_id: str, run_args: list[str], workers: int, root: Path,
                  *, new_session: bool) -> list[list[str]]:
    """tmux commands that create the swarm window and one log pane per worker."""
    import shlex

    metis = str(root / ".venv" / "bin" / "metis")
    session = session_name(contest_id)
    base = [metis, "swarm", "--database", str(database)]
    hold = "; echo; echo '[swarm finished - press Enter to close]'; read _"
    logs = database.parent / "swarm" / contest_id
    swarm = shlex.join([*base, "run", contest_id, *run_args]) + hold
    commands = [["tmux", "new-session", "-d", "-s", session, "-n", "swarm", "-c", str(root), swarm]
                if new_session else ["tmux", "new-window", "-d", "-t", session, "-n", "swarm", "-c", str(root), swarm]]
    for group in range(0, workers, 4):
        names = [f"w{index + 1}" for index in range(group, min(group + 4, workers))]
        window = "workers" if group == 0 else f"workers{group // 4 + 1}"

        def tail(name: str) -> str:
            path = shlex.quote(str(logs / f"{name}.log"))
            return f"mkdir -p {shlex.quote(str(logs))}; touch {path}; printf '[{name}]\\n'; tail -n 40 -F {path}"

        commands.append(["tmux", "new-window", "-d", "-t", session, "-n", window, "-c", str(root), tail(names[0])])
        for name in names[1:]:
            commands.append(["tmux", "split-window", "-d", "-t", f"{session}:{window}", "-c", str(root), tail(name)])
        commands.append(["tmux", "select-layout", "-t", f"{session}:{window}", "tiled"])
    return commands


def dashboard_window(database: Path, contest_id: str, root: Path) -> list[str]:
    import shlex

    command = shlex.join([str(root / ".venv" / "bin" / "metis"), "swarm", "--database", str(database),
                          "watch", contest_id])
    return ["tmux", "new-window", "-d", "-t", session_name(contest_id), "-n", "dashboard", "-c", str(root), command]


def tmux_plan(database: Path, contest_id: str, run_args: list[str], workers: int,
              root: Path | None = None) -> tuple[str, list[list[str]]]:
    """tmux commands for a swarm: swarm process, live dashboard, one log pane per worker."""
    root = (root or Path.cwd()).resolve()
    session = session_name(contest_id)
    commands = swarm_windows(database, contest_id, run_args, workers, root, new_session=True)
    commands.insert(1, dashboard_window(database, contest_id, root))
    commands.append(["tmux", "select-window", "-t", f"{session}:dashboard"])
    return session, commands


def tmux_windows(session: str) -> list[str] | None:
    """Window names of a tmux session, or None when it does not exist."""
    result = subprocess.run(["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
                            capture_output=True, text=True, check=False)
    return result.stdout.split() if result.returncode == 0 else None


def launch_tmux(database: Path, contest_id: str, run_args: list[str], workers: int) -> dict[str, Any]:
    if shutil.which("tmux") is None:
        raise ValueError("tmux is not installed (macOS: brew install tmux)")
    root = Path.cwd().resolve()
    session = session_name(contest_id)
    windows = tmux_windows(session)
    if windows is None:
        _, commands = tmux_plan(database, contest_id, run_args, workers, root)
    elif "swarm" in windows:
        raise ValueError(f"a swarm is already running in tmux session {session} (window 'swarm')")
    else:
        # A `./play` session for this contest: add the swarm windows to it.
        commands = swarm_windows(database, contest_id, run_args, workers, root, new_session=False)
        if "dashboard" not in windows:
            commands.append(dashboard_window(database, contest_id, root))
        commands.append(["tmux", "select-window", "-t", f"{session}:dashboard"])
    for command in commands:
        subprocess.run(command, check=True)
    attach = ["tmux", "switch-client", "-t", session] if os.environ.get("TMUX") else ["tmux", "attach", "-t", session]
    return {"tmux_session": session, "attach": " ".join(attach), "attach_command": attach}


HANDOFF_PROMPT = """METIS の大会 {name}（contest_id: {contest_id}）で、スウォームのワーカーが解法まで進めて
引き継いだ問題が {count} 問あります。1問ずつ順番に片付けてください。

共通の手順:
- 各問題の WriteUP と note に解法・送る値・ソルバーがある。まず読み、足りない部分だけ補う。
- 問題インスタンスが要る場合はブラウザで起動し、表示された host:port を
  `.venv/bin/metis remote grant RUN_ID HOST PORT --replace` で許可して `latest` 指定で接続する
  （古い接続先は自動で無効になる）。インスタンスはアカウントで同時1つなので、次の問題の前に停止を確認する。
- 提出はサイトの規約どおり（ブラウザ提出のサイトはフォームで提出し `metis web attest --candidate-file`）。
- 正解したら `metis contest update` で solved、`metis writeup save` で WriteUP を解答版に更新する。
- 実行ファイルは `metis sandbox` の中だけで動かす。

問題:
{items}
"""


def handoff(database: Path, contest_id: str) -> dict[str, Any]:
    """Challenges a worker brought to the last step that needs the operator's browser."""
    board = ContestBoard(database).board(contest_id)
    items = [item for item in board["challenges"] if item["state"] == "handoff"]
    with sqlite3.connect(database) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        writeups = dict(db.execute("SELECT challenge_id, path FROM ctf_writeups WHERE contest_id=?",
                                   (contest_id,)).fetchall()) if "ctf_writeups" in tables else {}
        endpoints: dict[str, list[str]] = {}
        if "remote_endpoints" in tables:
            columns = {row[1] for row in db.execute("PRAGMA table_info(remote_endpoints)")}
            active = " AND revoked=0" if "revoked" in columns else ""
            for item in items:
                if item.get("run_id"):
                    endpoints[item["challenge_id"]] = [
                        f"{host}:{port}" for host, port in db.execute(
                            "SELECT host, port FROM remote_endpoints WHERE run_id=?" + active + " ORDER BY idx",
                            (item["run_id"],))]
    output = []
    for item in sorted(items, key=lambda c: -c["points"]):
        output.append({"challenge_id": item["challenge_id"], "title": item["title"], "category": item["category"],
                       "points": item["points"], "url": item.get("url"), "run_id": item.get("run_id"),
                       "note": item.get("notes"), "writeup": writeups.get(item["challenge_id"]),
                       "granted_endpoints": endpoints.get(item["challenge_id"], [])})
    lines = []
    for number, item in enumerate(output, 1):
        lines.append(f"{number}. {item['challenge_id']} — {item['title']}（{item['category']}、{item['points']:g}点）")
        for label, key in (("URL", "url"), ("run", "run_id"), ("WriteUP", "writeup"), ("要点", "note")):
            if item[key]:
                lines.append(f"   - {label}: {item[key]}")
    prompt = HANDOFF_PROMPT.format(name=board["name"], contest_id=contest_id, count=len(output),
                                   items="\n".join(lines) or "（なし）")
    return {"contest_id": contest_id, "count": len(output), "challenges": output,
            "prompt": prompt if output else None,
            "next": "claude --chrome に prompt を渡す（metis swarm handoff CONTEST --prompt で本文だけ出力）"}
