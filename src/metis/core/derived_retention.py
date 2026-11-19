"""Explicit, bounded age policy for controller-generated run artifacts."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from metis.core.codex_session import CodexSession

MAX_RETENTION_RUNS = 100


def retain_derived(database: Path, *, older_than_days: int, apply: bool = False,
                   now: float | None = None) -> dict[str, Any]:
    """Preview or purge derived files for runs older than a fixed age.

    Each run is checked again by ``purge_derived`` under its operation and run
    locks. A failed run is reported and left for an explicit retry; no later run
    is silently skipped. The policy never removes original or user-added files.
    """
    if not 1 <= older_than_days <= 3650:
        raise ValueError("retention age must be 1 to 3650 days")
    if now is None:
        now = time.time()
    cutoff = now - older_than_days * 86_400
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT run_id FROM codex_sessions WHERE started <= ? "
            "ORDER BY started, run_id LIMIT ?", (cutoff, MAX_RETENTION_RUNS + 1),
        ).fetchall()
    if len(rows) > MAX_RETENTION_RUNS:
        raise ValueError("retention selection exceeds 100 runs")
    session = CodexSession(database)
    results: list[dict[str, Any]] = []
    for (run_id,) in rows:
        try:
            outcome = session.purge_derived(run_id, apply=apply)
            results.append({"run_id": run_id, "status": "applied" if apply else "preview",
                            "files": outcome["files"],
                            "manifest_entries_removed": outcome.get("manifest_entries_removed", 0)})
        except (ValueError, OSError, sqlite3.Error):
            results.append({"run_id": run_id, "status": "blocked"})
    return {"applied": apply, "older_than_days": older_than_days,
            "selected_runs": len(rows), "results": results}
