"""Persistent contest-wide prioritization for one operator coordinating AI agents."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from metis.core.codex_session import CodexSession

FORMATS = {"jeopardy", "attack-defense"}
STATES = {"queued", "investigating", "candidate", "reproduced", "blocked", "solved", "abandoned"}
HEALTH = {"unknown", "healthy", "degraded", "down"}
PATCH = {"unpatched", "testing", "deployed", "failed"}


class ContestBoard:
    def __init__(self, database: Path):
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_contests (
                contest_id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL,
                starts REAL, ends REAL, max_parallel INTEGER NOT NULL, created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_contest_challenges (
                contest_id TEXT NOT NULL, challenge_id TEXT NOT NULL, title TEXT NOT NULL,
                category TEXT NOT NULL, points REAL NOT NULL, solves INTEGER NOT NULL,
                estimated_minutes REAL NOT NULL, confidence REAL NOT NULL, state TEXT NOT NULL,
                run_id TEXT, prerequisites TEXT NOT NULL, service_health TEXT NOT NULL,
                patch_status TEXT NOT NULL, official_verified INTEGER NOT NULL,
                updated REAL NOT NULL, PRIMARY KEY(contest_id,challenge_id))""")

    def create(self, config: dict[str, Any]) -> dict[str, Any]:
        name = self._text(config.get("name"), "name", 2, 160)
        contest_format = str(config.get("format", "jeopardy"))
        if contest_format not in FORMATS:
            raise ValueError("unsupported contest format")
        max_parallel = int(config.get("max_parallel", 4))
        if not 1 <= max_parallel <= 8:
            raise ValueError("max_parallel must be between 1 and 8")
        starts = self._optional_number(config.get("starts_at"))
        ends = self._optional_number(config.get("ends_at"))
        if starts is not None and ends is not None and ends <= starts:
            raise ValueError("contest end must follow start")
        contest_id = uuid4().hex
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO ctf_contests VALUES (?,?,?,?,?,?,?)",
                       (contest_id, name, contest_format, starts, ends, max_parallel, time.time()))
        return {"contest_id": contest_id, "name": name, "format": contest_format,
                "max_parallel": max_parallel}

    def add(self, contest_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        self._contest(contest_id)
        if not 1 <= len(items) <= 500:
            raise ValueError("add between 1 and 500 challenges")
        rows = []
        for item in items:
            challenge_id = self._text(item.get("challenge_id"), "challenge_id", 1, 120)
            title = self._text(item.get("title"), "title", 1, 200)
            category = self._text(item.get("category", "misc"), "category", 1, 40)
            points = float(item.get("points", 1))
            solves = int(item.get("solves", 0))
            estimate = float(item.get("estimated_minutes", 30))
            confidence = float(item.get("confidence", 0.35))
            prerequisites = item.get("prerequisites", [])
            if (not 0 <= points <= 1_000_000 or solves < 0 or not 1 <= estimate <= 1440
                    or not 0 <= confidence <= 1):
                raise ValueError("invalid score, solve count, estimate or confidence")
            if (not isinstance(prerequisites, list) or len(prerequisites) > 32
                    or any(not isinstance(value, str) or len(value) > 120 for value in prerequisites)):
                raise ValueError("invalid prerequisites")
            rows.append((contest_id, challenge_id, title, category, points, solves, estimate,
                         confidence, "queued", None, json.dumps(prerequisites), "unknown",
                         "unpatched", 0, time.time()))
        with sqlite3.connect(self.database) as db:
            db.executemany("""INSERT INTO ctf_contest_challenges VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        return {"contest_id": contest_id, "added": len(rows)}

    def update(self, contest_id: str, challenge_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        contest = self._contest(contest_id)
        current = self._challenge(contest_id, challenge_id)
        allowed = {"points", "solves", "estimated_minutes", "confidence", "state", "run_id",
                   "service_health", "patch_status", "official_verified"}
        if not changes or set(changes) - allowed:
            raise ValueError("unsupported or empty challenge update")
        updated = dict(current)
        updated.update(changes)
        state = str(updated["state"])
        health = str(updated["service_health"])
        patch = str(updated["patch_status"])
        if "official_verified" in changes and not isinstance(changes["official_verified"], bool):
            raise TypeError("official_verified must be boolean")
        verified = bool(updated["official_verified"])
        if state not in STATES or health not in HEALTH or patch not in PATCH:
            raise ValueError("invalid challenge lifecycle value")
        if state == "solved" and not verified:
            raise ValueError("solved requires an official verified result")
        if state == "solved" and (not isinstance(updated["run_id"], str)
                                  or CodexSession(self.database).context(updated["run_id"])["status"]
                                  != "solved"):
            raise ValueError("solved requires a linked verified run")
        if contest["format"] != "attack-defense" and (
                "service_health" in changes or "patch_status" in changes):
            raise ValueError("service and patch state require attack-defense format")
        values = (float(updated["points"]), int(updated["solves"]),
                  float(updated["estimated_minutes"]), float(updated["confidence"]), state,
                  updated["run_id"], health, patch, int(verified), time.time(),
                  contest_id, challenge_id)
        if (not 0 <= values[0] <= 1_000_000 or values[1] < 0
                or not 1 <= values[2] <= 1440 or not 0 <= values[3] <= 1):
            raise ValueError("invalid score, solve count, estimate or confidence")
        with sqlite3.connect(self.database) as db:
            db.execute("""UPDATE ctf_contest_challenges SET points=?,solves=?,estimated_minutes=?,
                confidence=?,state=?,run_id=?,service_health=?,patch_status=?,official_verified=?,
                updated=? WHERE contest_id=? AND challenge_id=?""", values)
        return self._challenge(contest_id, challenge_id)

    def dispatch(self, contest_id: str) -> dict[str, Any]:
        contest = self._contest(contest_id)
        challenges = self._challenges(contest_id)
        solved = {item["challenge_id"] for item in challenges if item["state"] == "solved"}
        active = [item for item in challenges if item["state"] in
                  {"investigating", "candidate", "reproduced"}]
        slots = max(0, contest["max_parallel"] - len(active))
        eligible = []
        for item in challenges:
            if item["state"] != "queued" or not set(item["prerequisites"]).issubset(solved):
                continue
            item["priority"] = self._priority(contest, item)
            eligible.append(item)
        eligible.sort(key=lambda item: (-item["priority"], item["updated"], item["challenge_id"]))
        selected: list[dict[str, Any]] = []
        represented = {item["category"] for item in active}
        for item in eligible:
            if len(selected) >= slots:
                break
            if item["category"] not in represented:
                selected.append(item)
                represented.add(item["category"])
        for item in eligible:
            if len(selected) >= slots:
                break
            if item not in selected:
                selected.append(item)
        now = time.time()
        with sqlite3.connect(self.database) as db:
            for item in selected:
                db.execute("UPDATE ctf_contest_challenges SET state='investigating',updated=? "
                           "WHERE contest_id=? AND challenge_id=?", (now, contest_id,
                                                                    item["challenge_id"]))
        work = active + [{**item, "state": "investigating"} for item in selected]
        return {"contest_id": contest_id, "format": contest["format"],
                "active": [self._work_packet(contest, item) for item in work],
                "slots_remaining": max(0, contest["max_parallel"] - len(work)),
                "queue_remaining": len(eligible) - len(selected)}

    def board(self, contest_id: str) -> dict[str, Any]:
        contest = self._contest(contest_id)
        challenges = self._challenges(contest_id)
        counts = {state: sum(item["state"] == state for item in challenges) for state in STATES}
        score = sum(item["points"] for item in challenges if item["state"] == "solved")
        return {**contest, "score": score, "counts": counts, "challenges": challenges}

    @staticmethod
    def _priority(contest: dict[str, Any], item: dict[str, Any]) -> float:
        value_rate = item["points"] * max(item["confidence"], 0.05) / item["estimated_minutes"]
        if contest["format"] == "attack-defense":
            if item["service_health"] == "down":
                return 1_000_000 + value_rate
            if item["service_health"] == "degraded":
                return 500_000 + value_rate
            if item["patch_status"] in {"failed", "testing"}:
                return 100_000 + value_rate
        return value_rate

    @staticmethod
    def _work_packet(contest: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        if contest["format"] == "attack-defense" and item["service_health"] in {"down", "degraded"}:
            action = "restore_and_verify_service"
        elif contest["format"] == "attack-defense" and item["patch_status"] == "testing":
            action = "regression_check_patch"
        else:
            action = "investigate_challenge"
        return {"challenge_id": item["challenge_id"], "title": item["title"],
                "category": item["category"], "action": action, "run_id": item["run_id"],
                "timebox_minutes": min(30, item["estimated_minutes"]),
                "required_result": ["hypothesis", "evidence", "next_action", "blocker"]}

    def _contest(self, contest_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT contest_id,name,format,starts,ends,max_parallel FROM ctf_contests "
                             "WHERE contest_id=?", (contest_id,)).fetchone()
        if not row:
            raise ValueError("unknown contest")
        keys = ("contest_id", "name", "format", "starts_at", "ends_at", "max_parallel")
        return dict(zip(keys, row))

    def _challenge(self, contest_id: str, challenge_id: str) -> dict[str, Any]:
        rows = [item for item in self._challenges(contest_id) if item["challenge_id"] == challenge_id]
        if not rows:
            raise ValueError("unknown challenge")
        return rows[0]

    def _challenges(self, contest_id: str) -> list[dict[str, Any]]:
        columns = ("challenge_id", "title", "category", "points", "solves",
                   "estimated_minutes", "confidence", "state", "run_id", "prerequisites",
                   "service_health", "patch_status", "official_verified", "updated")
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT " + ",".join(columns) +
                              " FROM ctf_contest_challenges WHERE contest_id=? ORDER BY challenge_id",
                              (contest_id,)).fetchall()
        result = [dict(zip(columns, row)) for row in rows]
        for item in result:
            item["prerequisites"] = json.loads(item["prerequisites"])
            item["official_verified"] = bool(item["official_verified"])
        return result

    @staticmethod
    def _text(value: Any, field: str, minimum: int, maximum: int) -> str:
        if not isinstance(value, str) or not minimum <= len(value) <= maximum:
            raise ValueError(f"invalid {field}")
        return value

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        return None if value is None else float(value)
