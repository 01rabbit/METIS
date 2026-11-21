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
from metis.core.run_lock import run_lock


def abstract_text(value: str) -> str:
    """Reject obvious answer/token material; this is not a complete DLP system."""
    if re.search(r"[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}|(?:FLAG|flag)_[^\s<>\"']{4,200}", value):
        raise ValueError("store abstract methods, not flag-shaped values")
    # A quoted prompt such as 'password: ' is not a credential; a value of 4+ chars is.
    if re.search(r"\bBearer\s+\S{8,}|\b(?:password|token|cookie|api_key)\s*[:=]\s*(?![\'\"`),\]])\S{4,}",
                 value, re.IGNORECASE):
        raise ValueError("credential-like values are not knowledge (matched `password|token|cookie|api_key: "
                         "VALUE` or `Bearer VALUE`; describe it without the value)")
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
    source_split: Literal["practice", "competition", "heldout"] | None = None
    # Why the outcome holds (Issue #15): abstract basis, never the answer. METIS fills it from the
    # run when the author leaves it empty (official verdict for success, failed attempt for failure).
    evidence: str = Field(default="", max_length=1000)


def _validate_prior_source(
    db: sqlite3.Connection, payload: str, stored_split: str, created: float, target_started: float,
) -> None:
    try:
        card = TechniqueCard.model_validate_json(payload)
    except ValueError:
        raise ValueError("held-out memory snapshot lacks prior source") from None
    if (stored_split not in {"practice", "competition"} or card.source_split != stored_split
            or created > target_started):
        raise ValueError("held-out memory snapshot lacks prior source")
    if not db.execute(
        "SELECT 1 FROM pragma_table_info('codex_sessions') WHERE name='evaluation_split'",
    ).fetchone():
        raise ValueError("held-out memory snapshot lacks prior source")
    source = db.execute(
        "SELECT 1 FROM codex_sessions WHERE run_id=? AND evaluation_split=? AND started <= ?",
        (card.source_run_id, stored_split, created),
    ).fetchone()
    if source is None:
        raise ValueError("held-out memory snapshot lacks prior source")


def validate_heldout_snapshot_source(
    db: sqlite3.Connection, run_id: str, card_id: int, payload: str, digest: str,
) -> None:
    source = db.execute(
        "SELECT payload,digest,source_split,created FROM munin_cards WHERE id=?", (card_id,),
    ).fetchone()
    run = db.execute("SELECT started FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()
    if source is None or run is None or source[:2] != (payload, digest):
        raise ValueError("held-out memory snapshot lacks prior source")
    _validate_prior_source(db, payload, source[2], source[3], run[0])


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
            db.execute("""CREATE TABLE IF NOT EXISTS heldout_memory_snapshots (
                run_id TEXT NOT NULL, card_id INTEGER NOT NULL, payload TEXT NOT NULL,
                digest TEXT NOT NULL, PRIMARY KEY(run_id, card_id))""")
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
        source_context = self.session.context(card.source_run_id)
        actual_split = source_context.get("evaluation_split")
        if actual_split == "heldout" or card.source_split == "heldout":
            raise ValueError("held-out evaluation material cannot enter reusable memory")
        if actual_split not in {"practice", "competition"}:
            raise ValueError("unlisted source runs cannot enter reusable memory")
        if card.source_split is not None and card.source_split != actual_split:
            raise ValueError("knowledge source split must match its run classification")
        card = card.model_copy(update={"source_split": actual_split})
        for value in (card.title, card.summary, card.conditions, card.failure_reason, card.evidence):
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
        if not card.evidence:
            basis = {"success": "official verdict: correct (verified solve recorded in the source run)",
                     "failure": "observed failed attempt in the source run: " + card.failure_reason[:200],
                     "inconclusive": "no verified outcome in the source run"}[card.outcome]
            card = card.model_copy(update={"evidence": basis})
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

    def search_for_run(self, run_id: str, query: str, *, category: str | None = None,
                       limit: int = 5) -> list[dict]:
        """Retrieve cards according to the run's evaluation split.

        Held-out runs can receive only frozen cards with corroborated source sessions.
        Unlisted runs receive no cards. Keyword search removes answer-shaped values,
        credentials and long encoded blobs from untrusted challenge text.
        """
        context = self.session.context(run_id)
        split = context.get("evaluation_split")
        if split == "heldout":
            if not 1 <= limit <= 20:
                raise ValueError("invalid memory search bounds")
            with sqlite3.connect(self.database) as db:
                db.execute("BEGIN")
                rows = db.execute(
                    "SELECT card_id,payload,digest FROM heldout_memory_snapshots WHERE run_id=? "
                    "ORDER BY card_id", (run_id,),
                ).fetchall()
                for identity, payload, checksum in rows:
                    if hashlib.sha256(payload.encode()).hexdigest() != checksum:
                        raise ValueError("held-out memory snapshot digest mismatch")
                    validate_heldout_snapshot_source(db, run_id, identity, payload, checksum)
            return [{"id": identity, "card": json.loads(payload),
                     "treat_as": "frozen prior experience; check applicability"}
                    for identity, payload, _ in rows
                    if category is None or json.loads(payload).get("category") == category][:limit]
        if split not in {"practice", "competition"}:
            return []
        safe_query = re.sub(r"[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}|(?:FLAG|flag)_[^\s<>\"']{4,200}",
                            " ", query)
        safe_query = re.sub(r"\b(?:Bearer\s+\S+|(?:password|token|cookie|api_key)\s*[:=]\s*\S+)",
                            " ", safe_query, flags=re.IGNORECASE)
        safe_query = re.sub(r"[A-Za-z0-9_+/=-]{48,}", " ", safe_query)
        return self.search(safe_query[:1000], category=category, limit=limit)

    def freeze_for_heldout(self, run_id: str, card_ids: list[int]) -> dict:
        """Copy selected prior cards once, before a held-out run has any work events."""
        if not 1 <= len(card_ids) <= 20 or len(card_ids) != len(set(card_ids)):
            raise ValueError("invalid snapshot card selection")
        with run_lock(self.database, run_id):
            if self.session.context(run_id).get("evaluation_split") != "heldout":
                raise ValueError("snapshot requires a held-out run")
            events = self.session.store.read(run_id)
            if [event.status for event in events] != [
                RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED, RunStatus.PLANNING,
            ]:
                raise ValueError("snapshot must precede held-out work")
            with sqlite3.connect(self.database) as db:
                db.execute("BEGIN IMMEDIATE")
                started = db.execute("SELECT started FROM codex_sessions WHERE run_id=?",
                                     (run_id,)).fetchone()[0]
                if db.execute("SELECT 1 FROM heldout_memory_snapshots WHERE run_id=?", (run_id,)).fetchone():
                    raise ValueError("held-out memory is already frozen")
                rows = db.execute(
                    f"SELECT id,payload,digest,source_split,created FROM munin_cards WHERE id IN ({','.join('?' for _ in card_ids)})",
                    card_ids,
                ).fetchall()
                if len(rows) != len(card_ids) or any(
                    row[3] not in {"practice", "competition"} or row[4] > started for row in rows
                ):
                    raise ValueError("snapshot contains unavailable or held-out cards")
                for identity, payload, digest, source_split, created in rows:
                    if hashlib.sha256(payload.encode()).hexdigest() != digest:
                        raise ValueError("snapshot card digest mismatch")
                    _validate_prior_source(db, payload, source_split, created, started)
                    db.execute("INSERT INTO heldout_memory_snapshots(run_id,card_id,payload,digest) VALUES (?,?,?,?)",
                               (run_id, identity, payload, digest))
        return {"run_id": run_id, "card_ids": sorted(card_ids)}

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
