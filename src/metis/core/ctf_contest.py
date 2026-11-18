"""Persistent contest-wide prioritization for one operator coordinating AI agents."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from metis.core.codex_session import CodexSession
from metis.core.resources import dependency_report

FORMATS = {"jeopardy", "attack-defense"}
# handoff: the worker found the solution path but the last step needs the operator's signed-in
# browser (spawning an instance, a login) -- see `metis swarm handoff`.
RELEASE_STATES = {"queued", "handoff", "blocked", "abandoned", "candidate", "solved"}
STATES = {"queued", "investigating", "candidate", "reproduced", "handoff", "blocked", "solved", "abandoned"}
HEALTH = {"unknown", "healthy", "degraded", "down"}
PATCH = {"unpatched", "testing", "deployed", "failed"}


def _page_key(url: object) -> str | None:
    """Normalized page URL key (no query, fragment or trailing slash) for run matching."""
    if not isinstance(url, str) or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"url:{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def _sync_keys(challenge_id: object, page_url: object) -> list[str]:
    """Keys under which a web run can be matched to a board challenge."""
    if challenge_id is not None:
        return [f"id:{challenge_id}"]
    page = _page_key(page_url)
    if page is None:
        return []
    slug = urlsplit(str(page_url).strip()).path.rstrip("/").rsplit("/", 1)[-1]
    return [page, f"slug:{slug}"] if slug else [page]


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
            columns = {row[1] for row in db.execute("PRAGMA table_info(ctf_contest_challenges)")}
            # Swarm leasing and problem location (added later; migrate older boards in place).
            for name, kind in (("worker", "TEXT"), ("lease_until", "REAL"), ("sessions", "INTEGER NOT NULL DEFAULT 0"),
                               ("url", "TEXT"), ("adapter", "TEXT"), ("notes", "TEXT"),
                               ("timebox_until", "REAL")):
                if name not in columns:
                    db.execute(f"ALTER TABLE ctf_contest_challenges ADD COLUMN {name} {kind}")
            # Where the contest lives and the rules agents must respect (one row per contest).
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_contest_meta (
                contest_id TEXT PRIMARY KEY, platform TEXT NOT NULL, url TEXT, adapter TEXT,
                catalog TEXT NOT NULL, rules TEXT NOT NULL, refreshed REAL)""")

    def create(self, config: dict[str, Any]) -> dict[str, Any]:
        name = self._text(config.get("name"), "name", 2, 160)
        contest_format = str(config.get("format", "jeopardy"))
        if contest_format not in FORMATS:
            raise ValueError("unsupported contest format")
        max_parallel = int(config.get("max_parallel", 4))
        if not 1 <= max_parallel <= 16:
            raise ValueError("max_parallel must be between 1 and 16")
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

    # -- platform, rules and refresh --------------------------------------------------
    def new(self, url: str, name: str | None = None, *, max_parallel: int = 4) -> dict[str, Any]:
        """Create a contest from its URL with the platform's default rules."""
        from metis.core.ctf_platforms import detect

        detected = detect(url)
        host = url.split("//", 1)[-1].split("/", 1)[0]
        created = self.create({"name": name or host, "max_parallel": max_parallel})
        self.configure(created["contest_id"], {key: detected[key] for key in ("platform", "url", "adapter",
                                                                               "catalog", "rules")})
        return {**created, **self.meta(created["contest_id"]), "list_hint": detected["list_hint"]}

    def configure(self, contest_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Set platform/url/adapter/catalog and merge rules (unspecified fields are kept)."""
        from metis.core.ctf_platforms import GENERIC_RULES, validate_rules

        self._contest(contest_id)
        allowed = {"platform", "url", "adapter", "catalog", "rules", "name"}
        if not changes or set(changes) - allowed:
            raise ValueError("configure fields: " + ", ".join(sorted(allowed)))
        current = self.meta(contest_id)
        merged = {**current, **{key: value for key, value in changes.items() if key != "rules"}}
        rules = {**GENERIC_RULES, **current["rules"], **validate_rules(dict(changes.get("rules") or {}))}
        if merged["catalog"] not in {"ctfd", "rctf", "agent"}:
            raise ValueError("catalog must be ctfd, rctf or agent")
        if merged["adapter"] is not None and merged["adapter"] not in {"auto", "html", "ctfd", "rctf", "ksnctf"}:
            raise ValueError("invalid adapter")
        if merged["url"] is not None:
            self._text(merged["url"], "url", 8, 2048)
            if not str(merged["url"]).startswith(("http://", "https://")):
                raise ValueError("contest url must be http(s)")
        platform = self._text(merged["platform"], "platform", 1, 40)
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO ctf_contest_meta(contest_id,platform,url,adapter,catalog,rules,refreshed) "
                       "VALUES (?,?,?,?,?,?,?) ON CONFLICT(contest_id) DO UPDATE SET platform=excluded.platform, "
                       "url=excluded.url, adapter=excluded.adapter, catalog=excluded.catalog, rules=excluded.rules",
                       (contest_id, platform, merged["url"], merged["adapter"], merged["catalog"],
                        json.dumps(rules, ensure_ascii=False), current["refreshed"]))
            if "name" in changes:
                db.execute("UPDATE ctf_contests SET name=? WHERE contest_id=?",
                           (self._text(changes["name"], "name", 2, 160), contest_id))
        return self.meta(contest_id)

    def meta(self, contest_id: str) -> dict[str, Any]:
        from metis.core.ctf_platforms import GENERIC_RULES

        self._contest(contest_id)
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT platform,url,adapter,catalog,rules,refreshed FROM ctf_contest_meta "
                             "WHERE contest_id=?", (contest_id,)).fetchone()
            if row is None:
                # Older boards: infer the platform from challenge URLs when possible.
                found = db.execute("SELECT url FROM ctf_contest_challenges WHERE contest_id=? AND url IS NOT NULL "
                                   "LIMIT 1", (contest_id,)).fetchone()
        if row is None:
            if found:
                from metis.core.ctf_platforms import detect
                guess = detect(found[0])
                from metis.core.ctf_platforms import PLATFORMS
                return {"contest_id": contest_id, "platform": guess["platform"],
                        "url": PLATFORMS.get(guess["platform"], {}).get("list_url"),
                        "adapter": guess["adapter"], "catalog": guess["catalog"], "rules": guess["rules"],
                        "refreshed": None, "configured": False}
            return {"contest_id": contest_id, "platform": "unknown", "url": None, "adapter": None,
                    "catalog": "agent", "rules": dict(GENERIC_RULES), "refreshed": None, "configured": False}
        return {"contest_id": contest_id, "platform": row[0], "url": row[1], "adapter": row[2], "catalog": row[3],
                "rules": json.loads(row[4]), "refreshed": row[5], "configured": True}

    def refresh(self, contest_id: str, listing: list[dict[str, Any]]) -> dict[str, Any]:
        """Add challenges not on the board yet; refresh points/solves of known ones.

        Lifecycle state, runs and notes of existing challenges are never touched.
        """
        if not isinstance(listing, list) or len(listing) > 500 or any(not isinstance(item, dict) for item in listing):
            raise ValueError("listing must be an array of up to 500 challenge objects")
        known = {item["challenge_id"]: item for item in self._challenges(contest_id)}
        fresh = [item for item in listing if str(item.get("challenge_id")) not in known]
        seen: set[str] = set()
        unique = []
        for item in fresh:
            key = str(item.get("challenge_id"))
            if key not in seen:
                seen.add(key)
                unique.append({**item, "challenge_id": key})
        if unique:
            self.add(contest_id, unique)
        updated = []
        with sqlite3.connect(self.database, timeout=30) as db:
            for item in listing:
                current = known.get(str(item.get("challenge_id")))
                if current is None:
                    continue
                points, solves = item.get("points"), item.get("solves")
                changes = {}
                if isinstance(points, (int, float)) and 0 <= points <= 1_000_000 and points != current["points"]:
                    changes["points"] = float(points)
                if isinstance(solves, int) and solves >= 0 and solves != current["solves"]:
                    changes["solves"] = solves
                if isinstance(item.get("url"), str) and not current.get("url") \
                        and item["url"].startswith(("http://", "https://")) and len(item["url"]) <= 2048:
                    changes["url"] = item["url"]
                if changes:
                    assignments = ", ".join(f"{key}=?" for key in changes)
                    db.execute(f"UPDATE ctf_contest_challenges SET {assignments} WHERE contest_id=? AND "
                               "challenge_id=?", (*changes.values(), contest_id, current["challenge_id"]))
                    updated.append(current["challenge_id"])
            db.execute("UPDATE ctf_contest_meta SET refreshed=? WHERE contest_id=?", (time.time(), contest_id))
        return {"contest_id": contest_id, "added": [item["challenge_id"] for item in unique],
                "updated": updated, "unchanged": len(listing) - len(unique) - len(updated),
                "board_total": len(known) + len(unique)}

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
            url = item.get("url")
            adapter = item.get("adapter")
            if url is not None:
                url = self._text(url, "url", 8, 2048)
                if not url.startswith(("http://", "https://")):
                    raise ValueError("challenge url must be http(s)")
            if adapter is not None and adapter not in {"auto", "html", "ctfd", "rctf", "ksnctf"}:
                raise ValueError("invalid adapter")
            rows.append((contest_id, challenge_id, title, category, points, solves, estimate,
                         confidence, "queued", None, json.dumps(prerequisites), "unknown",
                         "unpatched", 0, time.time(), url, adapter))
        graph = {item["challenge_id"]: item["prerequisites"] for item in self._challenges(contest_id)}
        graph.update({row[1]: json.loads(row[10]) for row in rows})
        cycles = dependency_report(graph, {})["cycles"]
        if cycles:
            raise ValueError("prerequisites form a cycle: " + ", ".join(cycles[:10]))
        with sqlite3.connect(self.database) as db:
            db.executemany("""INSERT INTO ctf_contest_challenges (contest_id, challenge_id, title, category,
                points, solves, estimated_minutes, confidence, state, run_id, prerequisites, service_health,
                patch_status, official_verified, updated, url, adapter) VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        return {"contest_id": contest_id, "added": len(rows)}

    def update(self, contest_id: str, challenge_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        contest = self._contest(contest_id)
        current = self._challenge(contest_id, challenge_id)
        allowed = {"points", "solves", "estimated_minutes", "confidence", "state", "run_id",
                   "service_health", "patch_status", "official_verified", "category", "prerequisites"}
        if not changes:
            raise ValueError("empty challenge update")
        if set(changes) - allowed:
            raise ValueError("unsupported update fields: " + ", ".join(sorted(set(changes) - allowed))
                             + "; allowed: " + ", ".join(sorted(allowed)))
        if "category" in changes:
            self._text(changes["category"], "category", 1, 40)
        if "prerequisites" in changes:
            values = changes["prerequisites"]
            if (not isinstance(values, list) or len(values) > 32
                    or any(not isinstance(value, str) or len(value) > 120 for value in values)):
                raise ValueError("invalid prerequisites")
        if "run_id" in changes and changes["run_id"] is not None:
            CodexSession(self.database).context(changes["run_id"])  # must be an existing run
            self._check_binding(current, changes["run_id"])
        updated = dict(current)
        updated.update(changes)
        state = str(updated["state"])
        health = str(updated["service_health"])
        patch = str(updated["patch_status"])
        if "official_verified" in changes and not isinstance(changes["official_verified"], bool):
            raise TypeError("official_verified must be boolean")
        verified = bool(updated["official_verified"])
        if state not in STATES:
            raise ValueError("invalid state; allowed: " + ", ".join(sorted(STATES)))
        if health not in HEALTH or patch not in PATCH:
            raise ValueError("invalid service_health or patch_status")
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
            db.execute("UPDATE ctf_contest_challenges SET category=?, prerequisites=? "
                       "WHERE contest_id=? AND challenge_id=?",
                       (str(updated["category"]), json.dumps(updated["prerequisites"]), contest_id, challenge_id))
        return self._challenge(contest_id, challenge_id)

    def sync(self, contest_id: str, origin_url: str) -> dict[str, Any]:
        """Link existing web runs on one platform origin to board challenges by challenge ID.

        A challenge whose linked run is officially solved becomes ``solved``; otherwise the
        most recent run is linked so work resumes in it instead of a duplicate run.
        """
        from metis.core.ctf_http import origin  # Local import keeps the board independent of HTTP.

        self._contest(contest_id)
        platform = origin(origin_url)
        session = CodexSession(self.database)
        with sqlite3.connect(self.database) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_runs'").fetchone():
                return {"contest_id": contest_id, "linked": [], "solved": []}
            rows = db.execute("SELECT w.run_id, w.config, c.started FROM web_runs w "
                              "JOIN codex_sessions c ON c.run_id = w.run_id ORDER BY c.started").fetchall()
        runs: dict[str, list[tuple[str, str]]] = {}
        locations: dict[str, tuple[str | None, str | None]] = {}
        for run_id, raw, _ in rows:
            config = json.loads(raw)
            if config.get("auth_origin") != platform:
                continue
            # Platform-API runs carry the challenge ID; HTML-page runs (e.g. AlpacaHack) only
            # their page URL, so they are keyed by the URL and by its last path segment.
            keys = _sync_keys(config.get("challenge_id"), config.get("page_url"))
            if not keys:
                continue
            status = session.context(run_id)["status"]
            for key in keys:
                runs.setdefault(key, []).append((run_id, status))
                locations[key] = (config.get("page_url"), config.get("adapter"))
        linked, solved = [], []
        for item in self._challenges(contest_id):
            match = next((candidate for candidate in (
                f"id:{item['challenge_id']}", _page_key(item.get("url")), f"slug:{item['challenge_id']}")
                if candidate and candidate in runs), None)
            if match is None:
                continue
            candidates = runs[match]
            url, adapter = locations.get(match, (None, None))
            if url and not item.get("url"):
                # Give swarm workers the problem location without reopening anything.
                with sqlite3.connect(self.database, timeout=30) as db:
                    db.execute("UPDATE ctf_contest_challenges SET url=?, adapter=? WHERE contest_id=? AND "
                               "challenge_id=?", (url, adapter, contest_id, item["challenge_id"]))
            winners = [run for run in candidates if run[1] == "solved"]
            run_id, status = winners[-1] if winners else candidates[-1]
            if status == "solved":
                self.update(contest_id, item["challenge_id"],
                            {"run_id": run_id, "state": "solved", "official_verified": True})
                solved.append(item["challenge_id"])
            elif item["run_id"] != run_id:
                self.update(contest_id, item["challenge_id"], {"run_id": run_id})
                linked.append({"challenge_id": item["challenge_id"], "run_id": run_id, "status": status})
        return {"contest_id": contest_id, "solved": solved, "linked": linked,
                "next": "dispatch again; resume linked runs instead of reopening problems"}

    def _check_binding(self, challenge: dict[str, Any], run_id: str) -> None:
        """A run opened from the web must be the board challenge's own problem."""
        with sqlite3.connect(self.database) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='web_runs'").fetchone():
                return
            row = db.execute("SELECT config FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return  # Local intake: nothing to compare.
        config = json.loads(row[0])
        page = str(config.get("page_url") or "").rstrip("/")
        board_url = str(challenge.get("url") or "").rstrip("/")
        remote_id = config.get("challenge_id")
        id_matches = remote_id is not None and str(remote_id) == challenge["challenge_id"]
        url_matches = bool(board_url) and page == board_url
        url_known = bool(board_url) and config.get("adapter") not in {"ctfd", "rctf"}
        if remote_id is not None and not id_matches and not url_matches:
            raise ValueError("run belongs to another problem (challenge id differs)")
        if remote_id is None and url_known and not url_matches:
            raise ValueError("run belongs to another problem (problem URL differs)")

    def enforce_timebox(self, contest_id: str, *, now: float | None = None) -> list[str]:
        """Dispatched challenges past their timebox become ``blocked`` with a note; the
        operator then requeues or abandons them explicitly. Swarm leases are separate."""
        now = now or time.time()
        overdue = [item for item in self._challenges(contest_id)
                   if item["state"] == "investigating" and not item["worker"]
                   and item.get("timebox_until") and item["timebox_until"] < now]
        with sqlite3.connect(self.database, timeout=30) as db:
            for item in overdue:
                db.execute("UPDATE ctf_contest_challenges SET state='blocked', timebox_until=NULL, updated=?, "
                           "notes=? WHERE contest_id=? AND challenge_id=? AND state='investigating'",
                           (now, "timebox exceeded; record the blocker, then requeue or abandon explicitly",
                            contest_id, item["challenge_id"]))
        return [item["challenge_id"] for item in overdue]

    def dispatch(self, contest_id: str) -> dict[str, Any]:
        expired = self.enforce_timebox(contest_id)
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
                db.execute("UPDATE ctf_contest_challenges SET state='investigating',updated=?,timebox_until=? "
                           "WHERE contest_id=? AND challenge_id=?",
                           (now, now + 60 * min(30, item["estimated_minutes"]), contest_id, item["challenge_id"]))
        work = active + [{**item, "state": "investigating"} for item in selected]
        return {"contest_id": contest_id, "format": contest["format"],
                "active": [self._work_packet(contest, item) for item in work],
                "blocked_by_prerequisites": self._dependencies(challenges)["blocked"],
                "slots_remaining": max(0, contest["max_parallel"] - len(work)),
                "queue_remaining": len(eligible) - len(selected), "timebox_expired": expired}

    def contests(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.database) as db:
            ids = [row[0] for row in db.execute("SELECT contest_id FROM ctf_contests ORDER BY created")]
        output = []
        for contest_id in ids:
            board = self.board(contest_id)
            meta = self.meta(contest_id)
            output.append({"contest_id": contest_id, "name": board["name"], "format": board["format"],
                           "platform": meta["platform"], "url": meta["url"], "refreshed": meta["refreshed"],
                           "challenges": len(board["challenges"]), "score": board["score"],
                           "counts": {state: count for state, count in board["counts"].items() if count}})
        return output

    # -- swarm leasing ------------------------------------------------------------
    def claim(self, contest_id: str, worker: str, *, lease_seconds: int = 2400) -> dict[str, Any]:
        """Atomically lease the best queued challenge to one worker.

        Expired leases return to the queue first, so a crashed worker never strands
        a challenge. Categories already being worked are deprioritized for coverage.
        """
        self._text(worker, "worker", 1, 64)
        if not 60 <= lease_seconds <= 4 * 3600:
            raise ValueError("lease must be between 60 seconds and 4 hours")
        contest = self._contest(contest_id)
        now = time.time()
        db = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE ctf_contest_challenges SET state='queued', worker=NULL, lease_until=NULL, "
                       "updated=? WHERE contest_id=? AND state='investigating' AND worker IS NOT NULL "
                       "AND lease_until < ?", (now, contest_id, now))
            rows = db.execute("SELECT challenge_id, category, state, worker, prerequisites, points, confidence, "
                              "estimated_minutes, service_health FROM ctf_contest_challenges WHERE contest_id=?",
                              (contest_id,)).fetchall()
            solved = {row[0] for row in rows if row[2] == "solved"}
            leased = [row for row in rows if row[2] == "investigating" and row[3]]
            if len(leased) >= contest["max_parallel"]:
                db.execute("COMMIT")
                return {"contest_id": contest_id, "challenge": None, "reason": "all parallel slots are leased",
                        "active": len(leased)}
            busy = {row[1] for row in leased}
            eligible = []
            for row in rows:
                if row[2] != "queued" or not set(json.loads(row[4])).issubset(solved):
                    continue
                item = {"points": row[5], "confidence": row[6], "estimated_minutes": row[7], "service_health": row[8]}
                eligible.append((row[1] in busy, -self._priority(contest, item), row[0]))
            if not eligible:
                db.execute("COMMIT")
                return {"contest_id": contest_id, "challenge": None, "reason": "queue empty",
                        "active": len(leased)}
            eligible.sort()
            chosen = eligible[0][2]
            db.execute("UPDATE ctf_contest_challenges SET state='investigating', worker=?, lease_until=?, "
                       "sessions=sessions+1, updated=? WHERE contest_id=? AND challenge_id=?",
                       (worker, now + lease_seconds, now, contest_id, chosen))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return {"contest_id": contest_id, "challenge": self._challenge(contest_id, chosen),
                "lease_seconds": lease_seconds, "queued_remaining": len(eligible) - 1}

    def heartbeat(self, contest_id: str, challenge_id: str, worker: str, *, lease_seconds: int = 2400) -> dict:
        if not 60 <= lease_seconds <= 4 * 3600:
            raise ValueError("lease must be between 60 seconds and 4 hours")
        with sqlite3.connect(self.database, timeout=30) as db:
            changed = db.execute("UPDATE ctf_contest_challenges SET lease_until=? WHERE contest_id=? AND "
                                 "challenge_id=? AND worker=? AND state='investigating'",
                                 (time.time() + lease_seconds, contest_id, challenge_id, worker)).rowcount
        if not changed:
            raise ValueError("lease is not held by this worker")
        return {"contest_id": contest_id, "challenge_id": challenge_id, "lease_seconds": lease_seconds}

    def release(self, contest_id: str, challenge_id: str, worker: str, *, state: str,
                note: str | None = None) -> dict[str, Any]:
        """End a worker's lease, moving the challenge to its next lifecycle state."""
        from metis.core.ctf_knowledge import abstract_text

        current = self._challenge(contest_id, challenge_id)
        if current["worker"] not in {worker, None}:
            raise ValueError("lease is held by another worker")
        if state not in RELEASE_STATES:
            raise ValueError("release state must be one of " + ", ".join(sorted(RELEASE_STATES)))
        if note is not None:
            if len(note) > 500:
                raise ValueError("note exceeds 500 characters")
            abstract_text(note)
        changes: dict[str, Any] = {"state": state}
        if state == "solved":
            changes["official_verified"] = True
        self.update(contest_id, challenge_id, changes)
        with sqlite3.connect(self.database, timeout=30) as db:
            db.execute("UPDATE ctf_contest_challenges SET worker=NULL, lease_until=NULL, notes=COALESCE(?, notes) "
                       "WHERE contest_id=? AND challenge_id=?", (note, contest_id, challenge_id))
        return self._challenge(contest_id, challenge_id)

    def board(self, contest_id: str) -> dict[str, Any]:
        contest = self._contest(contest_id)
        challenges = self._challenges(contest_id)
        counts = {state: sum(item["state"] == state for item in challenges) for state in STATES}
        score = sum(item["points"] for item in challenges if item["state"] == "solved")
        dependencies = self._dependencies(challenges)
        return {**contest, "score": score, "counts": counts, "challenges": challenges,
                "blocked_by_prerequisites": dependencies["blocked"],
                "unknown_prerequisites": dependencies["unknown"]}

    @staticmethod
    def _dependencies(challenges: list[dict[str, Any]]) -> dict[str, Any]:
        """Queued work whose prerequisite was abandoned (directly or upstream) can never become
        eligible; report it instead of letting it wait silently."""
        report = dependency_report({item["challenge_id"]: item["prerequisites"] for item in challenges},
                                   {item["challenge_id"]: item["state"] for item in challenges},
                                   success=frozenset({"solved"}), failures=frozenset({"abandoned"}))
        queued = {item["challenge_id"] for item in challenges if item["state"] == "queued"}
        report["blocked"] = {key: value for key, value in report["blocked"].items() if key in queued}
        return report

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
                   "service_health", "patch_status", "official_verified", "updated",
                   "worker", "lease_until", "sessions", "url", "adapter", "notes", "timebox_until")
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
