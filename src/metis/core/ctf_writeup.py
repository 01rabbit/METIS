"""Per-CTF Markdown write-ups and a cross-CTF technique index.

Layout (relative to the repository root by default)::

    writeups/
      README.md                     # every CTF, with progress
      KNOWLEDGE.md                  # MUNIN technique cards grouped by category
      <ctf-slug>/
        README.md                   # problem table for that CTF
        <id>-<title-slug>.md        # one write-up per problem
        files/<id>/...              # scripts the write-up references

The agent supplies the narrative (summary, analysis, solution, flag, lessons,
scripts, techniques). METIS adds what it observed itself: official verdict
timeline, hypothesis history, distribution files with SHA-256, granted
endpoints and budget use. Write-ups contain the flag as supplied by the agent
(user decision). Technique cards derived from a write-up stay abstract: they
are what later challenges retrieve, so flag-shaped values are still refused
there.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeCategory, RunStatus
from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard

JST = dt.timezone(dt.timedelta(hours=9), "JST")
STATE_LABELS = {"solved": "解決済み", "queued": "未着手", "investigating": "調査中", "candidate": "候補あり",
                "reproduced": "再現済み", "handoff": "引き継ぎ待ち", "blocked": "ブロック中", "abandoned": "断念"}


class Technique(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=160)
    category: ChallengeCategory
    summary: str = Field(min_length=10, max_length=2000)
    conditions: str = Field(min_length=5, max_length=1000)
    outcome: Literal["success", "failure", "inconclusive"] | None = None
    failure_reason: str = Field(default="", max_length=1000)


class WriteupInput(BaseModel):
    """Narrative written by the agent; everything else is taken from METIS state."""

    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=10, max_length=4000)
    analysis: str = Field(default="", max_length=40_000)
    solution: str = Field(default="", max_length=60_000)
    flag: str | None = Field(default=None, max_length=512)
    lessons: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=16)
    references: list[str] = Field(default_factory=list, max_length=16)
    scripts: list[str] = Field(default_factory=list, max_length=16)
    techniques: list[Technique] = Field(default_factory=list, max_length=8)
    run_id: str | None = None
    source_split: Literal["practice", "competition"] = "practice"


def slug(value: str, limit: int = 60) -> str:
    text = re.sub(r"[^\w.-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-.")
    return (text or "untitled")[:limit]


def _time(value: float | str | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        try:
            seconds = dt.datetime.fromisoformat(value).timestamp()
        except ValueError:
            return value
    else:
        seconds = float(value)
    return dt.datetime.fromtimestamp(seconds, JST).strftime("%Y-%m-%d %H:%M JST")


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


class WriteupBook:
    def __init__(self, database: Path, root: Path = Path("writeups")):
        self.database = database
        self.root = root
        self.session = CodexSession(database)
        self.board = ContestBoard(database)
        self.knowledge = KnowledgeBase(database)
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_writeups (
                contest_id TEXT NOT NULL, challenge_id TEXT NOT NULL, run_id TEXT,
                path TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(contest_id, challenge_id))""")

    # -- facts from METIS state ----------------------------------------------------
    def _facts(self, run_id: str) -> dict[str, Any]:
        context = self.session.context(run_id)
        events = self.session.store.read(run_id)
        executing = [event for event in events if event.status == RunStatus.EXECUTING]
        solved = [event for event in events if event.status == RunStatus.SOLVED]
        operations: dict[str, int] = {}
        for event in executing:
            name = event.detail.get("operation", "?")
            operations[name] = operations.get(name, 0) + 1
        with sqlite3.connect(self.database) as db:
            stamps = dict(db.execute("SELECT sequence, timestamp FROM events WHERE run_id=?", (run_id,)).fetchall())
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            attempts = (db.execute("SELECT verdict, created, attempts FROM web_attempts WHERE run_id=? "
                                   "ORDER BY created", (run_id,)).fetchall() if "web_attempts" in tables else [])
            hypotheses = db.execute("SELECT status, summary, evidence, created FROM ctf_hypotheses WHERE run_id=? "
                                    "ORDER BY id", (run_id,)).fetchall() if "ctf_hypotheses" in tables else []
            web = (db.execute("SELECT config, salt FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
                   if "web_runs" in tables else None)
            correct = ([row[0] for row in db.execute("SELECT digest FROM web_attempts WHERE run_id=? "
                                                     "AND verdict='correct'", (run_id,))]
                       if "web_attempts" in tables else [])
        files = []
        root = self.session.artifact_root(run_id)
        for name in context["challenge"]["artifacts"]:
            if root is None:
                break
            path = root / name
            try:
                content = path.read_bytes()
            except OSError:
                continue
            files.append({"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        config = json.loads(web[0]) if web else {}
        return {
            "status": context["status"], "title": context["challenge"]["title"],
            "solved_at": stamps.get(solved[-1].sequence) if solved else None,
            "verification": solved[-1].detail.get("verification") if solved else None,
            "started": stamps.get(events[0].sequence) if events else None,
            "last": stamps.get(events[-1].sequence) if events else None,
            "actions": len(executing), "operations": operations,
            "attempts": [{"verdict": verdict, "time": created, "count": count} for verdict, created, count in attempts],
            "hypotheses": [{"status": status, "summary": summary, "evidence": evidence, "time": created}
                           for status, summary, evidence, created in hypotheses],
            "files": files, "endpoints": context["network_tools"],
            "page_url": config.get("page_url"), "origins": config.get("origins", []),
            "salt": web[1] if web else None, "correct_digests": correct,
        }

    @staticmethod
    def flag_check(facts: dict[str, Any] | None, flag: str | None) -> str:
        """Compare a flag with the officially accepted submission without storing either."""
        if not flag:
            return "none"
        if not facts or not facts.get("salt") or not facts.get("correct_digests"):
            return "unverifiable"
        digest = hmac.new(bytes.fromhex(facts["salt"]), flag.encode(), hashlib.sha256).hexdigest()
        return "match" if any(hmac.compare_digest(digest, item) for item in facts["correct_digests"]) else "mismatch"

    # -- writing -------------------------------------------------------------------
    def save(self, contest_id: str, challenge_id: str, entry: WriteupInput) -> dict[str, Any]:
        entry = WriteupInput.model_validate(entry.model_dump())
        contest = self.board._contest(contest_id)
        challenge = self.board._challenge(contest_id, challenge_id)
        run_id = entry.run_id or challenge.get("run_id")
        facts = self._facts(run_id) if run_id else None
        directory = self.root / slug(contest["name"])
        directory.mkdir(parents=True, exist_ok=True)
        identity, title_slug = slug(challenge_id, 40), slug(challenge["title"])
        # Numeric IDs (ksnctf) read best with the title; slug IDs (AlpacaHack) usually are the title.
        name = (f"{identity}.md" if title_slug in {identity, "untitled"} or identity.startswith(title_slug)
                or title_slug.startswith(identity) else f"{identity}-{title_slug}.md")
        path = directory / name
        with sqlite3.connect(self.database) as db:
            previous = db.execute("SELECT path FROM ctf_writeups WHERE contest_id=? AND challenge_id=?",
                                  (contest_id, challenge_id)).fetchone()
        if previous and Path(previous[0]) != path and Path(previous[0]).is_file() and not path.exists():
            Path(previous[0]).rename(path)  # Keep one file per problem when the naming changes.

        copied = []
        for script in entry.scripts:
            source = Path(script)
            resolved = source.resolve()
            allowed = (Path(".metis-state/work").resolve(), self.root.resolve())
            if not resolved.is_file() or not any(resolved.is_relative_to(base) for base in allowed):
                raise ValueError("scripts must be files under .metis-state/work/: " + script)
            if resolved.stat().st_size > 512 * 1024:
                raise ValueError("script exceeds 512 KiB: " + script)
            target_dir = directory / "files" / slug(challenge_id, 12)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / slug(source.name, 80)
            if resolved != target.resolve():
                shutil.copyfile(resolved, target)
            copied.append(target.relative_to(directory).as_posix())

        learned = []
        for technique in entry.techniques:
            outcome = technique.outcome or ("success" if facts and facts["status"] == "solved" else "inconclusive")
            if not run_id:
                learned.append({"title": technique.title, "stored": False, "error": "no linked run"})
                continue
            try:
                result = self.knowledge.remember(TechniqueCard(
                    title=technique.title, category=technique.category, summary=technique.summary,
                    conditions=technique.conditions, failure_reason=technique.failure_reason,
                    outcome=outcome, source_run_id=run_id, source_split=entry.source_split))
                learned.append({"title": technique.title, **result})
            except ValueError as exc:
                learned.append({"title": technique.title, "stored": False,
                                "error": (str(exc).splitlines() or ["rejected"])[0][:200]})

        check = self.flag_check(facts, entry.flag)
        path.write_text(self._render(contest, challenge, run_id, facts, entry, copied, check), encoding="utf-8")
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO ctf_writeups(contest_id,challenge_id,run_id,path,updated) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(contest_id,challenge_id) DO UPDATE SET run_id=excluded.run_id,"
                       "path=excluded.path,updated=excluded.updated",
                       (contest_id, challenge_id, run_id, str(path), time.time()))
        index = self.index(contest_id)
        knowledge = self.export_knowledge()
        return {"path": str(path), "flag_check": check, "scripts": copied, "techniques": learned,
                "ctf_index": index["path"], "knowledge_index": knowledge["path"]}

    def _render(self, contest: dict[str, Any], challenge: dict[str, Any], run_id: str | None,
                facts: dict[str, Any] | None, entry: WriteupInput, scripts: list[str],
                check: str = "none") -> str:
        solved = facts is not None and facts["status"] == "solved"
        state = "solved" if solved else challenge["state"]
        status = STATE_LABELS.get(state, state)
        if solved and facts is not None:
            status += f"（公式判定で正解: {_time(facts['solved_at'])}）"
        lines = [f"# {challenge['title']}", "",
                 "| 項目 | 内容 |", "| --- | --- |",
                 f"| 大会 | {_cell(contest['name'])} |",
                 f"| 問題番号 | {_cell(challenge['challenge_id'])} |",
                 f"| カテゴリ | {_cell(challenge['category'])} |",
                 f"| 配点 | {challenge['points']:g} |",
                 f"| 状態 | {_cell(status)} |",
                 f"| Flag | {'`' + entry.flag.replace('`', '') + '`' if entry.flag else '-'} |"]
        labels = {"match": "公式判定で正解した文字列と一致", "mismatch": "⚠ 公式判定で正解した文字列と不一致",
                  "unverifiable": "照合不可（このrunに公式の正解判定がない）"}
        if check in labels:
            lines.append(f"| Flag照合 | {labels[check]} |")
        if entry.tags:
            lines.append(f"| タグ | {_cell(', '.join(entry.tags))} |")
        if facts and facts.get("page_url"):
            lines.append(f"| 問題URL | {_cell(facts['page_url'])} |")
        if run_id:
            lines.append(f"| METIS run | `{run_id}` |")
        lines += ["", "## 概要", "", entry.summary.strip(), ""]
        if entry.analysis.strip():
            lines += ["## 解析", "", entry.analysis.strip(), ""]
        if entry.solution.strip():
            lines += ["## 解法", "", entry.solution.strip(), ""]
        if scripts:
            lines += ["## 使用したスクリプト", ""]
            lines += [f"- [{Path(item).name}]({item})" for item in scripts]
            lines.append("")
        if entry.lessons.strip() or entry.techniques:
            lines += ["## 学び・再利用できる手法", ""]
            if entry.lessons.strip():
                lines += [entry.lessons.strip(), ""]
            for technique in entry.techniques:
                lines += [f"- **{technique.title}**（{technique.category.value}）: {technique.summary}",
                          f"  - 適用条件: {technique.conditions}"]
            lines.append("")
        if entry.references:
            lines += ["## 参考", ""] + [f"- {item}" for item in entry.references] + [""]
        if facts:
            lines += ["## METISの記録", "",
                      f"- 期間: {_time(facts['started'])} 〜 {_time(facts['last'])}",
                      f"- 使用アクション数: {facts['actions']}"
                      + ("（" + ", ".join(f"{key} ×{value}" for key, value in sorted(facts["operations"].items()))
                         + "）" if facts["operations"] else "")]
            if facts["verification"]:
                lines.append(f"- 判定方式: {facts['verification']}")
            if facts["attempts"]:
                lines += ["", "### 提出履歴", "", "| 時刻 | 判定 | 回数 |", "| --- | --- | --- |"]
                lines += [f"| {_time(item['time'])} | {item['verdict']} | {item['count']} |"
                          for item in facts["attempts"]]
            if facts["hypotheses"]:
                lines += ["", "### 仮説の変遷", "", "| 時刻 | 状態 | 仮説 | 根拠 |", "| --- | --- | --- | --- |"]
                lines += [f"| {_time(item['time'])} | {item['status']} | {_cell(item['summary'])} | "
                          f"{_cell(item['evidence'])} |" for item in facts["hypotheses"]]
            if facts["files"]:
                lines += ["", "### 配布ファイル・取得データ", "", "| ファイル | サイズ | SHA-256 |", "| --- | --- | --- |"]
                lines += [f"| {_cell(item['name'])} | {item['size']:,} | `{item['sha256']}` |"
                          for item in facts["files"]]
            if facts["endpoints"]:
                lines += ["", "### 接続先", ""]
                lines += [f"- {item['host']}:{item['port']}{' (TLS)' if item['tls'] else ''}"
                          for item in facts["endpoints"]]
            lines.append("")
        lines += [f"<sub>METIS writeup — 更新: {_time(time.time())}</sub>", ""]
        return "\n".join(lines)

    # -- indexes -------------------------------------------------------------------
    def index(self, contest_id: str) -> dict[str, Any]:
        state = self.board.board(contest_id)
        directory = self.root / slug(state["name"])
        directory.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as db:
            written = dict(db.execute("SELECT challenge_id, path FROM ctf_writeups WHERE contest_id=?",
                                      (contest_id,)).fetchall())
        challenges = state["challenges"]

        def order(item: dict[str, Any]) -> tuple[int, str]:
            identity = item["challenge_id"]
            return (int(identity), "") if identity.isdigit() else (1 << 30, identity)

        solved = [item for item in challenges if item["state"] == "solved"]
        lines = [f"# {state['name']}", "",
                 f"- 形式: {state['format']}",
                 f"- 進捗: {len(solved)} / {len(challenges)} 問解決、{state['score']:g} 点",
                 f"- WriteUP: {len(written)} 件", "",
                 "| # | 問題 | カテゴリ | 配点 | 状態 | WriteUP |", "| --- | --- | --- | --- | --- | --- |"]
        for item in sorted(challenges, key=order):
            link = "-"
            if item["challenge_id"] in written:
                link = f"[WriteUP]({Path(written[item['challenge_id']]).name})"
            lines.append(f"| {_cell(item['challenge_id'])} | {_cell(item['title'])} | {_cell(item['category'])} | "
                         f"{item['points']:g} | {STATE_LABELS.get(item['state'], item['state'])} | {link} |")
        lines += ["", f"<sub>METIS — 更新: {_time(time.time())}</sub>", ""]
        path = directory / "README.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self._root_index()
        return {"path": str(path)}

    def _root_index(self) -> None:
        with sqlite3.connect(self.database) as db:
            contests = db.execute("SELECT contest_id FROM ctf_contests ORDER BY created").fetchall()
        lines = ["# CTF WriteUPs", "", "| CTF | 形式 | 解決 | 得点 | WriteUP |", "| --- | --- | --- | --- | --- |"]
        for (contest_id,) in contests:
            state = self.board.board(contest_id)
            directory = slug(state["name"])
            with sqlite3.connect(self.database) as db:
                count = db.execute("SELECT COUNT(*) FROM ctf_writeups WHERE contest_id=?", (contest_id,)).fetchone()[0]
            if not count and not (self.root / directory).exists():
                continue
            solved = sum(item["state"] == "solved" for item in state["challenges"])
            lines.append(f"| [{_cell(state['name'])}]({directory}/README.md) | {state['format']} | "
                         f"{solved} / {len(state['challenges'])} | {state['score']:g} | {count} |")
        lines += ["", "大会をまたいだ手法の一覧は [KNOWLEDGE.md](KNOWLEDGE.md) を参照。", ""]
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "README.md").write_text("\n".join(lines), encoding="utf-8")

    def export_knowledge(self) -> dict[str, Any]:
        """Render every reusable MUNIN technique card, linked to the write-up it came from."""
        with sqlite3.connect(self.database) as db:
            cards = db.execute("SELECT payload FROM munin_cards WHERE source_split != 'heldout' ORDER BY category, id"
                               ).fetchall()
            links = {run_id: path for run_id, path in
                     db.execute("SELECT run_id, path FROM ctf_writeups WHERE run_id IS NOT NULL").fetchall()}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for (payload,) in cards:
            card = json.loads(payload)
            grouped.setdefault(card["category"], []).append(card)
        lines = ["# 手法ナレッジ（MUNIN）", "",
                 (f"{sum(len(items) for items in grouped.values())} 件の手法カード。METISは新しい問題の取得時に"
                 "このカードを検索し、似た問題の手法を提示します（`metis memory search`）。"), ""]
        labels = {"success": "成功", "failure": "失敗", "inconclusive": "未確定"}
        for category in sorted(grouped):
            lines += [f"## {category}", ""]
            for card in grouped[category]:
                source = links.get(card["source_run_id"])
                origin = ""
                if source:
                    origin = f" — [出典]({Path(source).relative_to(self.root).as_posix()})" \
                        if Path(source).is_relative_to(self.root) else ""
                lines += [f"### {card['title']}（{labels.get(card['outcome'], card['outcome'])}）{origin}", "",
                          card["summary"], "", f"- 適用条件: {card['conditions']}"]
                if card.get("failure_reason"):
                    lines.append(f"- 失敗理由: {card['failure_reason']}")
                lines.append("")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "KNOWLEDGE.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return {"path": str(path), "cards": sum(len(items) for items in grouped.values())}

    def missing(self, contest_id: str) -> dict[str, Any]:
        """Solved challenges that still lack a write-up (for backfilling)."""
        state = self.board.board(contest_id)
        with sqlite3.connect(self.database) as db:
            written = {row[0] for row in db.execute("SELECT challenge_id FROM ctf_writeups WHERE contest_id=?",
                                                    (contest_id,))}
        return {"contest_id": contest_id,
                "solved_without_writeup": [{"challenge_id": item["challenge_id"], "title": item["title"],
                                            "run_id": item["run_id"]}
                                           for item in state["challenges"]
                                           if item["state"] == "solved" and item["challenge_id"] not in written]}
