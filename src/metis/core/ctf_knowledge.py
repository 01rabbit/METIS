"""Local MUNIN technique cards and concise, evidence-based hypothesis revisions."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeCategory, Contract, RunStatus


def abstract_text(value: str) -> str:
    """Reject obvious answer/token material; this is not a complete DLP system."""
    if re.search(r"[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}|(?:FLAG|flag)_[^\s<>\"']{4,200}", value):
        raise ValueError("store abstract methods, not flag-shaped values")
    if re.search(r"\bBearer\s+\S+|\b(?:password|token|cookie|api_key)\s*[:=]\s*\S+", value, re.IGNORECASE):
        raise ValueError("credential-like values are not knowledge")
    if re.search(r"[A-Za-z0-9_+/=-]{48,}|[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}", value):
        raise ValueError("raw encoded payloads are not knowledge")
    return value


class TechniqueCard(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=3, max_length=160)
    category: ChallengeCategory
    summary: str = Field(min_length=10, max_length=2000)
    conditions: str = Field(min_length=5, max_length=1000)
    failure_reason: str = Field(default="", max_length=1000)
    outcome: Literal["success", "failure", "inconclusive"]
    source_run_id: str = Field(min_length=1, max_length=80)
    source_split: Literal["practice", "competition", "heldout"] = "competition"


class KnowledgeBase:
    def __init__(self, database: Path):
        self.session = CodexSession(database)
        self.database = database
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS munin_cards (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL, category TEXT NOT NULL,
                title TEXT NOT NULL, summary TEXT NOT NULL, conditions TEXT NOT NULL,
                failure_reason TEXT NOT NULL, outcome TEXT NOT NULL, source_split TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE, created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ctf_hypotheses (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
                summary TEXT NOT NULL, evidence TEXT NOT NULL, next_step TEXT NOT NULL,
                created REAL NOT NULL)""")
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS munin_fts USING fts5(title, summary, conditions, failure_reason)")
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False

    def reason(self, run_id: str, *, summary: str, evidence: str, next_step: str,
               status: str = "revised") -> dict:
        self.session._session(run_id)
        if status not in {"proposed", "revised", "rejected", "supported"}:
            raise ValueError("invalid hypothesis status")
        for value in (summary, evidence, next_step):
            if not 5 <= len(value) <= 2000:
                raise ValueError("provide concise, substantive hypothesis, evidence and next step")
            abstract_text(value)
        with sqlite3.connect(self.database) as db:
            cursor = db.execute("INSERT INTO ctf_hypotheses(run_id,status,summary,evidence,next_step,created) VALUES (?,?,?,?,?,?)",
                                (run_id, status, summary, evidence, next_step, time.time()))
            identity = cursor.lastrowid
        return {"run_id": run_id, "hypothesis_id": identity, "status": status}

    def hypotheses(self, run_id: str) -> list[dict]:
        self.session._session(run_id)
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT id,status,summary,evidence,next_step FROM ctf_hypotheses WHERE run_id=? ORDER BY id DESC LIMIT 20",
                              (run_id,)).fetchall()
        return [{"id": identity, "status": status, "summary": summary, "evidence": evidence,
                 "next_step": next_step} for identity, status, summary, evidence, next_step in rows]

    def remember(self, card: TechniqueCard) -> dict:
        card = TechniqueCard.model_validate(card.model_dump())
        if card.source_split == "heldout":
            raise ValueError("held-out evaluation material cannot enter reusable memory")
        for value in (card.title, card.summary, card.conditions, card.failure_reason):
            abstract_text(value)
        events = self.session.store.read(card.source_run_id)
        if not events:
            raise ValueError("knowledge requires an existing evidence run")
        if card.outcome == "success" and events[-1].status != RunStatus.SOLVED:
            raise ValueError("successful technique cards require a verified solve")
        if card.outcome == "failure" and not card.failure_reason:
            raise ValueError("failed methods need an evidence-based failure reason")
        if card.outcome == "failure" and not any(
            event.detail.get("tool_ok") == "false" or "incorrect" in event.detail.get("reason", "")
            or event.detail.get("reason") in {"candidate_unverified", "candidate_rejected"}
            for event in events
        ):
            raise ValueError("failed technique cards require an observed failed attempt")
        payload = card.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with sqlite3.connect(self.database) as db:
            found = db.execute("SELECT id FROM munin_cards WHERE digest=?", (digest,)).fetchone()
            if found:
                return {"id": found[0], "stored": False, "already_known": True}
            cursor = db.execute("INSERT INTO munin_cards(payload,category,title,summary,conditions,failure_reason,outcome,source_split,digest,created) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (payload, card.category.value, card.title, card.summary, card.conditions,
                                 card.failure_reason, card.outcome, card.source_split, digest, time.time()))
            identity = cursor.lastrowid
            if self.fts:
                db.execute("INSERT INTO munin_fts(rowid,title,summary,conditions,failure_reason) VALUES (?,?,?,?,?)",
                           (identity, card.title, card.summary, card.conditions, card.failure_reason))
        return {"id": identity, "stored": True, "digest": digest}

    def search(self, query: str, *, category: str | None = None, limit: int = 5) -> list[dict]:
        if len(query) > 1000 or not 1 <= limit <= 20:
            raise ValueError("invalid memory search bounds")
        if category is not None:
            ChallengeCategory(category)
        rows = []
        with sqlite3.connect(self.database) as db:
            terms = re.findall(r"\w{2,40}", query)[:12]
            if self.fts and terms:
                match = " OR ".join('"' + term + '"' for term in terms)
                rows = db.execute(
                    "SELECT c.id,c.payload FROM munin_fts JOIN munin_cards c ON c.id=munin_fts.rowid "
                    "WHERE munin_fts MATCH ? AND c.source_split != 'heldout' AND (? IS NULL OR c.category=?) "
                    "ORDER BY bm25(munin_fts),c.id DESC LIMIT ?", (match, category, category, limit),
                ).fetchall()
            if not rows:
                pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                rows = db.execute(
                    "SELECT id,payload FROM munin_cards WHERE source_split != 'heldout' "
                    "AND (? IS NULL OR category=?) AND (title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' "
                    "OR conditions LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT ?",
                    (category, category, pattern, pattern, pattern, limit),
                ).fetchall()
        return [{"id": identity, "card": json.loads(payload), "treat_as": "untrusted prior experience; check applicability"}
                for identity, payload in rows]
