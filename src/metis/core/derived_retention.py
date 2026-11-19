"""Explicit, bounded age policy for controller-generated run artifacts."""
from __future__ import annotations

import os
import resource
import sqlite3
import time
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

from metis.core.codex_session import (
    MAX_DERIVED_ARTIFACTS_PER_RUN,
    CodexSession,
    DerivedArtifactLimitError,
)
from metis.core.run_lock import operation_lock, run_lock

MAX_RETENTION_RUNS = 100
LOCK_FDS_PER_RUN = 2
LOCK_FD_RESERVE = 16
LOCK_BATCH_TIMEOUT_SECONDS = 15.0
TERMINAL_STATUSES = {"solved", "cancelled", "error", "policy_denied"}


def safe_lock_batch_capacity(soft_limit: int, open_fds: int) -> int:
    """Return how many two-FD per-run lock pairs fit with a fixed reserve."""
    available = max(0, soft_limit - open_fds - LOCK_FD_RESERVE)
    return min(MAX_RETENTION_RUNS, available // LOCK_FDS_PER_RUN)


def _open_fd_count() -> int:
    for path in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    raise OSError("cannot determine open descriptor count")


def _retention_lock_capacity() -> int:
    soft_limit, _hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft_limit == resource.RLIM_INFINITY:
        return MAX_RETENTION_RUNS
    return safe_lock_batch_capacity(int(soft_limit), _open_fd_count())


def retain_derived(database: Path, *, older_than_days: int, apply: bool = False,
                   now: float | None = None) -> dict[str, Any]:
    """Preview or purge derived files for runs older than a fixed age.

    Apply preflights the complete bounded selection while holding all selected
    run locks. If any run exceeds the per-run artifact limit, no selected run is
    purged. The per-run purge rechecks its own limit before every unlink.
    """
    if not 1 <= older_than_days <= 3650:
        raise ValueError("retention age must be 1 to 3650 days")
    if now is None:
        now = time.time()
    cutoff = now - older_than_days * 86_400
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT run_id FROM codex_sessions WHERE started <= ? "
            "ORDER BY started, run_id LIMIT ?", (cutoff, MAX_RETENTION_RUNS + 1),
        ).fetchall()
    if len(rows) > MAX_RETENTION_RUNS:
        raise ValueError("retention selection exceeds 100 runs")
    session = CodexSession(database)
    results: list[dict[str, Any]] = []

    def inspect_run(run_id: str) -> tuple[dict[str, Any], dict[str, object] | None]:
        try:
            outcome = session.purge_derived(run_id, apply=False)
            return ({"run_id": run_id, "status": "preview",
                     "files": outcome["files"],
                     "manifest_entries_removed": outcome.get("manifest_entries_removed", 0)},
                    outcome)
        except DerivedArtifactLimitError as exc:
            return ({"run_id": run_id, "status": "overflow",
                     "artifact_count": exc.count, "artifact_limit": exc.limit}, None)
        except (ValueError, OSError, sqlite3.Error):
            return ({"run_id": run_id, "status": "blocked"}, None)

    lock_capacity: int | None = None
    if not apply:
        for (run_id,) in rows:
            result, _outcome = inspect_run(run_id)
            results.append(result)
    else:
        # Avoid waiting on live or resumable runs: only terminal candidates are
        # locked, and purge_derived rechecks eligibility while holding those locks.
        terminal_ids: list[str] = []
        for (run_id,) in rows:
            try:
                events = session.store.read(run_id)
            except (OSError, sqlite3.Error, ValueError):
                results.append({"run_id": run_id, "status": "blocked"})
                continue
            if events and events[-1].status.value in TERMINAL_STATUSES:
                terminal_ids.append(str(run_id))
            else:
                results.append({"run_id": run_id, "status": "blocked"})

        try:
            lock_capacity = _retention_lock_capacity()
        except (OSError, ValueError):
            lock_capacity = None
        if lock_capacity is None:
            results.extend({"run_id": run_id, "status": "capacity_unavailable"}
                           for run_id in sorted(terminal_ids))
        elif len(terminal_ids) > lock_capacity:
            results.extend({"run_id": run_id, "status": "capacity_exceeded",
                            "selected_runs": len(terminal_ids),
                            "lock_capacity": lock_capacity}
                           for run_id in sorted(terminal_ids))
        else:
            # Hold the complete bounded selection through preflight and apply.
            # The per-run methods reacquire these locks reentrantly.
            run_ids = sorted(terminal_ids)
            preflight: dict[str, tuple[dict[str, Any], dict[str, object] | None]] = {}
            stack = ExitStack()
            lock_deadline = time.monotonic() + LOCK_BATCH_TIMEOUT_SECONDS
            try:
                for run_id in run_ids:
                    remaining = lock_deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("retention lock acquisition timed out")
                    stack.enter_context(operation_lock(database, run_id, timeout=remaining))
                    remaining = lock_deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("retention lock acquisition timed out")
                    stack.enter_context(run_lock(database, run_id, timeout=remaining))
            except (TimeoutError, OSError, ValueError):
                stack.close()
                results.extend({"run_id": run_id, "status": "blocked"} for run_id in run_ids)
            else:
                with stack:
                    for run_id in run_ids:
                        preflight[run_id] = inspect_run(run_id)
                    if any(result["status"] == "overflow" for result, _ in preflight.values()):
                        for run_id in run_ids:
                            result, _outcome = preflight[run_id]
                            if result["status"] == "preview":
                                results.append({"run_id": run_id, "status": "not_applied",
                                                "artifact_count": len(result["files"]),
                                                "artifact_limit": MAX_DERIVED_ARTIFACTS_PER_RUN})
                            else:
                                results.append(result)
                    else:
                        for run_id in run_ids:
                            result, _outcome = preflight[run_id]
                            if result["status"] == "blocked":
                                results.append(result)
                                continue
                            try:
                                outcome = session.purge_derived(run_id, apply=True)
                                results.append({"run_id": run_id, "status": "applied",
                                                "files": outcome["files"],
                                                "manifest_entries_removed": outcome.get(
                                                    "manifest_entries_removed", 0)})
                            except DerivedArtifactLimitError as exc:
                                # The selected run locks prevent controller writers
                                # changing counts after preflight; remain fail-closed
                                # if an external actor changes the database.
                                results.append({"run_id": run_id, "status": "overflow",
                                                "artifact_count": exc.count,
                                                "artifact_limit": exc.limit})
                            except (ValueError, OSError, sqlite3.Error):
                                results.append({"run_id": run_id, "status": "blocked"})

    return {"applied": apply, "older_than_days": older_than_days,
            "selected_runs": len(rows),
            "artifact_limit_per_run": MAX_DERIVED_ARTIFACTS_PER_RUN,
            "batch_lock_capacity": lock_capacity,
            "results": results}
