"""Shared resource leases, scoped permits and dependency checks.

* Resources: named capacities (``sandbox``, ``browser``, ``submit:ctfd`` ...) shared by every
  process that uses the same SQLite file. A holder acquires its *whole* resource set in one
  ``BEGIN IMMEDIATE`` transaction or nothing, so two holders never deadlock on partial sets.
  A resource without a configured capacity is not limited (existing behavior stays the same
  until an operator configures one).
* Lease lifetime: a lease taken through :meth:`ResourceBroker.lease` records its process and
  host and is renewed by a heartbeat while the ``with`` block runs, so a long sandbox or render
  never outlives a fixed TTL. :meth:`ResourceBroker.reap` releases an expired lease only when its
  recorded holder process is confirmed gone on this host; leases without a verifiable holder
  (task leases held across commands) are kept and reported, never silently freed. Releasing
  someone else's lease is an owner operation (:meth:`ResourceBroker.force_release`).
* Permits and owner operations: issuing a permit, force-releasing a lease and changing a
  capacity require the owner key (``<state dir>/private/owner.key``, 0600, created by
  ``metis permit init``); only its SHA-256 is stored in the database. The key is the authority
  boundary inside METIS. It holds against specialists that cannot read the state directory
  (Codex specialist turns run with the user's home denied by the OS sandbox); a process running
  as the same OS user with unrestricted file access can read the key or write the database
  directly, so for such agents the boundary is OS-level isolation, not this check.
  Consumption is atomic, so two callers cannot both spend the last use.
* Dependencies: validate a dependency map (unknown references, cycles) and report which nodes
  are ready, waiting, or blocked because a prerequisite ended without success.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_.:")
MAX_CAPACITY = 64
MAX_LEASE_SECONDS = 4 * 3600
MAX_PERMIT_SECONDS = 24 * 3600
MAX_PERMIT_USES = 100


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or not set(value) <= NAME_CHARS:
        raise ValueError(f"{field} must be 1-80 characters of a-z 0-9 - _ . :")
    return value


def _connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(database, timeout=30, isolation_level=None)


def owner_key_path(database: Path) -> Path:
    return database.parent / "private" / "owner.key"


def _owner_table(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS metis_owner (id INTEGER PRIMARY KEY CHECK (id = 1), "
               "key_sha256 TEXT NOT NULL, created REAL NOT NULL)")


def init_owner_key(database: Path) -> dict[str, Any]:
    """Create the owner key once (0600 file in a 0700 directory) and record only its digest."""
    path = owner_key_path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(database)) as db:
        _owner_table(db)
        stored = db.execute("SELECT key_sha256 FROM metis_owner WHERE id=1").fetchone()
    if stored is not None:
        return {"owner_key": str(path), "created": False}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    key = secrets.token_hex(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(key + "\n")
    with closing(_connect(database)) as db:
        db.execute("BEGIN IMMEDIATE")
        _owner_table(db)
        if db.execute("SELECT 1 FROM metis_owner WHERE id=1").fetchone() is None:
            db.execute("INSERT INTO metis_owner VALUES (1, ?, ?)",
                       (hashlib.sha256(key.encode()).hexdigest(), time.time()))
        db.execute("COMMIT")
    return {"owner_key": str(path), "created": True}


def read_owner_key(database: Path, path: Path | None = None) -> str:
    """The key from ``METIS_OWNER_KEY`` or the key file; never printed."""
    value = os.environ.get("METIS_OWNER_KEY")
    if value:
        return value.strip()
    target = path or owner_key_path(database)
    try:
        return target.read_text().strip()
    except OSError:
        raise PermissionError("owner key unavailable; Daybreak runs `metis permit init` once") from None


def require_owner(database: Path, key: str | None) -> None:
    with closing(_connect(database)) as db:
        _owner_table(db)
        row = db.execute("SELECT key_sha256 FROM metis_owner WHERE id=1").fetchone()
    if row is None:
        raise PermissionError("no owner key is registered; Daybreak runs `metis permit init` once")
    presented = hashlib.sha256((key or "").encode()).hexdigest()
    if not key or not hmac.compare_digest(presented, row[0]):
        raise PermissionError("owner key required for this operation")


def _alive(pid: int | None, host: str | None) -> bool | None:
    """True/False when the holder can be checked on this host, None when it cannot."""
    if pid is None or host != socket.gethostname():
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ResourceBroker:
    def __init__(self, database: Path):
        self.database = database
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS resource_capacity (
                name TEXT PRIMARY KEY, capacity INTEGER NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS resource_leases (
                lease_id TEXT NOT NULL, name TEXT NOT NULL, holder TEXT NOT NULL, units INTEGER NOT NULL,
                acquired REAL NOT NULL, expires REAL NOT NULL, purpose TEXT,
                PRIMARY KEY(lease_id, name))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(resource_leases)")}
            for column in ("pid INTEGER", "host TEXT"):
                if column.split()[0] not in columns:
                    db.execute("ALTER TABLE resource_leases ADD COLUMN " + column)
            db.execute("""CREATE TABLE IF NOT EXISTS resource_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, lease_id TEXT, name TEXT, event TEXT NOT NULL,
                detail TEXT, time REAL NOT NULL)""")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = _connect(self.database)
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    @staticmethod
    def _event(db: sqlite3.Connection, lease_id: str | None, name: str | None, event: str,
               detail: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO resource_events (lease_id, name, event, detail, time) VALUES (?,?,?,?,?)",
                   (lease_id, name, event, json.dumps(detail or {}, sort_keys=True), time.time()))

    def configure(self, name: str, capacity: int | None, *, owner_key: str | None) -> dict[str, Any]:
        """Owner only: set a capacity (``None`` removes the limit). Never shrinks below leased units."""
        require_owner(self.database, owner_key)
        name = _name(name, "resource")
        with self._transaction() as db:
            if capacity is None:
                db.execute("DELETE FROM resource_capacity WHERE name=?", (name,))
            else:
                if not 1 <= capacity <= MAX_CAPACITY:
                    raise ValueError(f"capacity must be 1..{MAX_CAPACITY}")
                used = db.execute("SELECT COALESCE(SUM(units),0) FROM resource_leases WHERE name=?",
                                  (name,)).fetchone()[0]
                if capacity < used:
                    raise ValueError(f"cannot shrink {name} below the {used} unit(s) currently leased")
                db.execute("INSERT INTO resource_capacity VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                           "capacity=excluded.capacity, updated=excluded.updated", (name, capacity, time.time()))
            self._event(db, None, name, "configured", {"capacity": capacity})
        return {"resource": name, "capacity": capacity}

    def try_acquire(self, holder: str, request: Mapping[str, int], *, ttl: int = 900,
                    purpose: str | None = None, pid: int | None = None) -> str | None:
        """Lease every requested unit or none. Returns the lease id, or ``None`` if it does not fit."""
        if not isinstance(holder, str) or not 1 <= len(holder) <= 120 or not holder.isprintable():
            raise ValueError("holder must be 1-120 printable characters")
        if not request or len(request) > 16:
            raise ValueError("request 1..16 resources")
        wanted = {_name(name, "resource"): units for name, units in request.items()}
        if any(not isinstance(units, int) or isinstance(units, bool) or not 1 <= units <= MAX_CAPACITY
               for units in wanted.values()):
            raise ValueError("units must be positive integers")
        if not 1 <= ttl <= MAX_LEASE_SECONDS:
            raise ValueError(f"lease ttl must be 1..{MAX_LEASE_SECONDS} seconds")
        now = time.time()
        with self._transaction() as db:
            for name, units in wanted.items():
                row = db.execute("SELECT capacity FROM resource_capacity WHERE name=?", (name,)).fetchone()
                if row is None:
                    continue
                used = db.execute("SELECT COALESCE(SUM(units),0) FROM resource_leases WHERE name=?",
                                  (name,)).fetchone()[0]
                if used + units > row[0]:
                    return None
            lease_id = uuid4().hex
            for name, units in wanted.items():
                db.execute("INSERT INTO resource_leases (lease_id, name, holder, units, acquired, expires, purpose, "
                           "pid, host) VALUES (?,?,?,?,?,?,?,?,?)",
                           (lease_id, name, holder, units, now, now + ttl, (purpose or "")[:200], pid,
                            socket.gethostname() if pid is not None else None))
            self._event(db, lease_id, None, "acquired", {"holder": holder, "resources": wanted})
        return lease_id

    def acquire(self, holder: str, request: Mapping[str, int], *, ttl: int = 900, wait: float = 0.0,
                poll: float = 0.25, purpose: str | None = None, pid: int | None = None) -> str:
        """Like :meth:`try_acquire`, but wait up to ``wait`` seconds; raise if it never fits."""
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            lease_id = self.try_acquire(holder, request, ttl=ttl, purpose=purpose, pid=pid)
            if lease_id is not None:
                return lease_id
            if time.monotonic() >= deadline:
                raise RuntimeError("resource busy: " + ", ".join(sorted(request)) +
                                   " (see `metis resource status`)")
            time.sleep(poll)

    def renew(self, lease_id: str, *, ttl: int = 900) -> bool:
        if not 1 <= ttl <= MAX_LEASE_SECONDS:
            raise ValueError(f"lease ttl must be 1..{MAX_LEASE_SECONDS} seconds")
        with self._transaction() as db:
            changed = db.execute("UPDATE resource_leases SET expires=? WHERE lease_id=?",
                                 (time.time() + ttl, lease_id)).rowcount
        return changed > 0

    def release(self, lease_id: str, *, reason: str = "released") -> bool:
        """Release a lease by its id. Holders release their own lease; others use force_release."""
        with self._transaction() as db:
            changed = db.execute("DELETE FROM resource_leases WHERE lease_id=?", (lease_id,)).rowcount
            if changed:
                self._event(db, lease_id, None, "released", {"reason": reason[:200]})
        return changed > 0

    def force_release(self, lease_id: str, *, owner_key: str | None, reason: str) -> bool:
        """Owner only: free someone else's lease after confirming its holder stopped."""
        require_owner(self.database, owner_key)
        if not reason.strip():
            raise ValueError("force release needs the reason the holder is known to be stopped")
        return self.release(lease_id, reason="forced: " + reason)

    def reap(self, *, now: float | None = None) -> dict[str, list[str]]:
        """Release expired leases whose recorded holder process is confirmed gone on this host.

        Expired leases whose holder is alive, on another host, or not recorded are kept and
        returned under ``kept``; elapsed time alone never frees capacity.
        """
        moment = time.time() if now is None else now
        reaped: list[str] = []
        kept: list[str] = []
        with self._transaction() as db:
            rows = db.execute("SELECT lease_id, MAX(pid), MAX(host) FROM resource_leases WHERE expires < ? "
                              "GROUP BY lease_id ORDER BY lease_id", (moment,)).fetchall()
            for lease_id, pid, host in rows:
                if _alive(pid, host) is False:
                    db.execute("DELETE FROM resource_leases WHERE lease_id=?", (lease_id,))
                    self._event(db, lease_id, None, "reaped", {"reason": "lease expired and holder process gone"})
                    reaped.append(lease_id)
                else:
                    kept.append(lease_id)
        return {"reaped": reaped, "kept": kept}

    @contextmanager
    def lease(self, holder: str, request: Mapping[str, int], *, ttl: int = 900, wait: float = 0.0,
              purpose: str | None = None) -> Iterator[str | None]:
        """Hold a lease for a ``with`` block, renewed by a heartbeat until the block exits.

        Yields ``None`` when no requested resource is limited.
        """
        if not self.limited(request):
            yield None
            return
        lease_id = self.acquire(holder, request, ttl=ttl, wait=wait, purpose=purpose, pid=os.getpid())
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(max(1.0, ttl / 3)):
                try:
                    if not self.renew(lease_id, ttl=ttl):
                        return
                except sqlite3.Error:
                    continue

        beat = threading.Thread(target=heartbeat, name="metis-lease-heartbeat", daemon=True)
        beat.start()
        try:
            yield lease_id
        finally:
            stop.set()
            beat.join(timeout=5)
            self.release(lease_id)

    def limited(self, request: Mapping[str, int]) -> bool:
        names = [_name(name, "resource") for name in request]
        with self._db() as db:
            return any(db.execute("SELECT 1 FROM resource_capacity WHERE name=?", (name,)).fetchone()
                       for name in names)

    def status(self) -> dict[str, Any]:
        now = time.time()
        with self._db() as db:
            capacities = {name: capacity for name, capacity in db.execute(
                "SELECT name, capacity FROM resource_capacity ORDER BY name")}
            leases = [{"lease_id": row[0], "resource": row[1], "holder": row[2], "units": row[3],
                       "acquired": row[4], "expires": row[5], "expired": row[5] < now, "purpose": row[6] or None,
                       "holder_alive": _alive(row[7], row[8])}
                      for row in db.execute("SELECT lease_id, name, holder, units, acquired, expires, purpose, "
                                            "pid, host FROM resource_leases ORDER BY acquired, name")]
        resources = []
        for name in sorted(set(capacities) | {lease["resource"] for lease in leases}):
            used = sum(lease["units"] for lease in leases if lease["resource"] == name)
            capacity = capacities.get(name)
            resources.append({"resource": name, "capacity": capacity, "leased": used,
                              "free": None if capacity is None else max(0, capacity - used)})
        return {"resources": resources, "leases": leases}


class ScopedPermits:
    """Exact, expiring, counted authority for actions that change something outside METIS."""

    def __init__(self, database: Path):
        self.database = database
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS scoped_permits (
                permit_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task TEXT NOT NULL, resource TEXT NOT NULL,
                action TEXT NOT NULL, reason TEXT NOT NULL, issued REAL NOT NULL, expires REAL NOT NULL,
                uses INTEGER NOT NULL, remaining INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS scoped_permit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id TEXT NOT NULL, event TEXT NOT NULL,
                time REAL NOT NULL)""")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = _connect(self.database)
        try:
            yield db
        finally:
            db.close()

    def issue(self, run_id: str, task: str, resource: str, action: str, reason: str, *,
              owner_key: str | None, ttl: int = 300, uses: int = 1) -> dict[str, Any]:
        """Owner only: the presented key must match the registered owner key."""
        require_owner(self.database, owner_key)
        for value, field in ((run_id, "run"), (task, "task"), (resource, "resource"), (action, "action")):
            if not isinstance(value, str) or not value or "*" in value or len(value) > 120:
                raise ValueError(f"permit needs an exact {field} (no wildcards)")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError("permit needs a reason (1..500 characters)")
        if not 1 <= ttl <= MAX_PERMIT_SECONDS or not 1 <= uses <= MAX_PERMIT_USES:
            raise ValueError(f"ttl must be 1..{MAX_PERMIT_SECONDS} s and uses 1..{MAX_PERMIT_USES}")
        permit_id = uuid4().hex
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO scoped_permits VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                       (permit_id, run_id, task, resource, action, reason.strip(), now, now + ttl, uses, uses))
            db.execute("INSERT INTO scoped_permit_log (permit_id, event, time) VALUES (?,?,?)",
                       (permit_id, "issued", now))
            db.execute("COMMIT")
        return {"permit_id": permit_id, "run_id": run_id, "task": task, "resource": resource, "action": action,
                "expires": now + ttl, "uses": uses}

    def consume(self, permit_id: str, run_id: str, task: str, resource: str, action: str) -> None:
        """Spend one use of a permit that matches exactly; raise ``PermissionError`` otherwise."""
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE scoped_permits SET remaining=remaining-1 WHERE permit_id=? AND run_id=? AND task=? "
                "AND resource=? AND action=? AND expires>? AND remaining>0 AND revoked=0",
                (permit_id, run_id, task, resource, action, now)).rowcount
            if changed == 1:
                db.execute("INSERT INTO scoped_permit_log (permit_id, event, time) VALUES (?,?,?)",
                           (permit_id, "consumed", now))
            db.execute("COMMIT")
        if changed != 1:
            raise PermissionError("a current owner-issued permit for exactly this run/task/resource/action "
                                  "is required")

    def revoke(self, permit_id: str) -> bool:
        """Anyone may revoke (it only removes authority)."""
        with self._db() as db:
            changed = db.execute("UPDATE scoped_permits SET revoked=1 WHERE permit_id=? AND revoked=0",
                                 (permit_id,)).rowcount
            if changed:
                db.execute("INSERT INTO scoped_permit_log (permit_id, event, time) VALUES (?,?,?)",
                           (permit_id, "revoked", time.time()))
        return changed > 0

    def list(self, run_id: str | None = None) -> list[dict[str, Any]]:
        now = time.time()
        query = ("SELECT permit_id, run_id, task, resource, action, reason, issued, expires, uses, remaining, "
                 "revoked FROM scoped_permits")
        params: tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE run_id=?"
            params = (run_id,)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY issued", params).fetchall()
        return [{"permit_id": row[0], "run_id": row[1], "task": row[2], "resource": row[3], "action": row[4],
                 "reason": row[5], "issued": row[6], "expires": row[7], "uses": row[8], "remaining": row[9],
                 "active": not row[10] and row[7] > now and row[9] > 0} for row in rows]


TERMINAL_FAILURES = frozenset({"failed", "blocked", "cancelled", "abandoned", "timed_out"})


def dependency_report(dependencies: Mapping[str, list[str]], states: Mapping[str, str], *,
                      success: frozenset[str] = frozenset({"done", "solved", "completed"}),
                      failures: frozenset[str] = TERMINAL_FAILURES) -> dict[str, Any]:
    """Classify nodes by their prerequisites.

    ``unknown`` lists references to nodes that do not exist, ``cycles`` lists nodes on a cycle,
    ``blocked`` maps each node to the prerequisites that ended without success (directly or
    through a blocked ancestor), ``waiting`` maps nodes to unfinished prerequisites, and
    ``ready`` lists nodes whose prerequisites all succeeded.
    """
    nodes = set(dependencies)
    unknown = sorted({f"{node}->{dep}" for node, deps in dependencies.items() for dep in deps if dep not in nodes})
    colour: dict[str, int] = {}
    on_cycle: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        colour[node] = 1
        stack.append(node)
        for dep in dependencies.get(node, []):
            if dep not in nodes:
                continue
            if colour.get(dep) == 1:
                on_cycle.update(stack[stack.index(dep):])
            elif colour.get(dep) is None:
                visit(dep, stack)
        stack.pop()
        colour[node] = 2

    for node in sorted(nodes):
        if colour.get(node) is None:
            visit(node, [])

    blocked: dict[str, list[str]] = {}

    def failed_ancestors(node: str, seen: frozenset[str]) -> list[str]:
        found: set[str] = set()
        for dep in dependencies.get(node, []):
            if dep not in nodes or dep in seen:
                continue
            if states.get(dep) in failures:
                found.add(dep)
            else:
                found.update(failed_ancestors(dep, seen | {dep}))
        return sorted(found)

    waiting: dict[str, list[str]] = {}
    ready: list[str] = []
    for node in sorted(nodes):
        if node in on_cycle:
            continue
        culprits = failed_ancestors(node, frozenset({node}))
        if culprits:
            blocked[node] = culprits
            continue
        pending = [dep for dep in dependencies.get(node, []) if dep in nodes and states.get(dep) not in success]
        missing = [dep for dep in dependencies.get(node, []) if dep not in nodes]
        if pending or missing:
            waiting[node] = sorted(pending + missing)
        else:
            ready.append(node)
    return {"unknown": unknown, "cycles": sorted(on_cycle), "blocked": blocked, "waiting": waiting,
            "ready": ready}
