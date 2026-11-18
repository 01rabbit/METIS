"""Connection ledger for external consumers (SIEM searches, remote sessions).

Daybreak first leases a resource to one ``(run, task)`` holder (:meth:`lease_task`). A consumer
can only start inside that lease, at most one connection per leased unit, and a state-changing
action also spends one exact scoped permit in the same transaction. A task cannot be finished
while one of its connections has not been confirmed stopped, so a lost cancel keeps its slot until
an operator reconciles it; elapsed time alone never frees it.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from metis.core.resources import ResourceBroker, ScopedPermits

SENSITIVE_ENV = re.compile(r"(?:PASSWORD|PASSWD|SSHPASS|TOKEN|SECRET|API_KEY|PRIVATE_KEY)$", re.IGNORECASE)
SENSITIVE_KEY = re.compile(r"^(?:password|passwd|api[_-]?key|secret|(?:access_|refresh_)?token|authorization"
                           r"|cookie|set-cookie|private_key)$", re.IGNORECASE)


def redact(value: Any) -> str:
    """Remove registered secret values and credential-shaped text before anything is stored."""
    text = str(value)
    for name, secret in os.environ.items():
        if SENSITIVE_ENV.search(name) and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"-----BEGIN [\w ]*PRIVATE KEY-----.*?-----END [\w ]*PRIVATE KEY-----", "[REDACTED KEY]", text,
                  flags=re.DOTALL)
    text = re.sub(r"(?i)(\b(?:password|passwd|api[_-]?key|token|secret|authorization|cookie)\b\s*[=:]\s*)"
                  r"([^\s,;]+)", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\bBearer\s+[\w.\-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    try:
        structured = json.loads(text)
    except (ValueError, TypeError):
        return text

    def scrub(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: "[REDACTED]" if SENSITIVE_KEY.fullmatch(str(key)) else scrub(child)
                    for key, child in item.items()}
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return item

    if isinstance(structured, (dict, list)):
        return json.dumps(scrub(structured), ensure_ascii=False)
    return text


def holder(run: str, task: str) -> str:
    return f"{run}/{task}"


class ConnectionLedger:
    def __init__(self, database: Path):
        self.database = database
        self.broker = ResourceBroker(database)
        self.permits = ScopedPermits(database)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS blue_connections (
                id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL, resource TEXT NOT NULL,
                protocol TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL, pid INTEGER,
                started REAL NOT NULL, finished REAL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS blue_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, task TEXT, sender TEXT NOT NULL,
                recipient TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL)""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    # -- Daybreak (owner) operations --------------------------------------------------------
    def lease_task(self, run: str, task: str, resources: dict[str, int], *, ttl: int = 3600) -> str:
        lease = self.broker.try_acquire(holder(run, task), resources, ttl=ttl, purpose="task lease")
        if lease is None:
            raise PermissionError("resource busy; lease it when another task finishes")
        self.message(run, task, "owner", task, "lease", json.dumps({"lease_id": lease, "resources": resources}))
        return lease

    def finish_task(self, run: str, task: str) -> list[str]:
        """Release the task's leases. Refused while a connection is not confirmed stopped."""
        with self.connect() as db:
            active = db.execute("SELECT id FROM blue_connections WHERE run=? AND task=? AND state!='stopped'",
                                (run, task)).fetchall()
            leases = sorted({row[0] for row in db.execute(
                "SELECT lease_id FROM resource_leases WHERE holder=?", (holder(run, task),))})
        if active:
            raise ValueError("stop or reconcile active connections before finishing this task")
        for lease in leases:
            self.broker.release(lease, reason="task finished")
        return leases

    # -- consumer operations ---------------------------------------------------------------
    def begin_connection(self, run: str, task: str, resource: str, protocol: str, action: str, write: bool,
                         grant: str | None) -> str:
        """Reserve the consumer before launch, atomically with permit consumption."""
        cid = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as db:
            units = db.execute("SELECT COALESCE(SUM(units),0) FROM resource_leases WHERE holder=? AND name=?",
                               (holder(run, task), resource)).fetchone()[0]
            if not units:
                raise PermissionError("Daybreak must lease this resource to the task first")
            active = db.execute("SELECT COUNT(*) FROM blue_connections WHERE run=? AND task=? AND resource=? "
                                "AND state!='stopped'", (run, task, resource)).fetchone()[0]
            if active >= units:
                raise PermissionError("all leased connection units are in use")
            if write:
                spent = db.execute(
                    "UPDATE scoped_permits SET remaining=remaining-1 WHERE permit_id=? AND run_id=? AND task=? "
                    "AND resource=? AND action=? AND expires>? AND remaining>0 AND revoked=0",
                    (grant or "", run, task, resource, action, now)).rowcount
                if spent != 1:
                    raise PermissionError("a current owner-issued permit for this exact action is required")
                db.execute("INSERT INTO scoped_permit_log (permit_id, event, time) VALUES (?,?,?)",
                           (grant, "consumed", now))
            db.execute("INSERT INTO blue_connections VALUES (?,?,?,?,?,?,?,NULL,?,NULL)",
                       (cid, run, task, resource, protocol, action, "starting", now))
        return cid

    def connection_state(self, cid: str, state: str, pid: int | None = None) -> None:
        if state not in ("running", "stopped"):
            raise ValueError("invalid connection state")
        with self.transaction() as db:
            db.execute("UPDATE blue_connections SET state=?, pid=COALESCE(?, pid), finished=? WHERE id=?",
                       (state, pid, time.time() if state == "stopped" else None, cid))

    def message(self, run: str, task: str | None, sender: str, recipient: str, kind: str, body: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT INTO blue_messages (run, task, sender, recipient, kind, body, created) "
                       "VALUES (?,?,?,?,?,?,?)", (run, task, sender, recipient, kind, redact(body)[:65_536],
                                                  time.time()))

    def report(self, run: str) -> dict[str, Any]:
        with self.connect() as db:
            connections = [dict(row) for row in db.execute(
                "SELECT * FROM blue_connections WHERE run=? ORDER BY started", (run,))]
            messages = [dict(row) for row in db.execute(
                "SELECT * FROM blue_messages WHERE run=? ORDER BY id", (run,))]
        return {"run": run, "connections": connections, "messages": messages}
