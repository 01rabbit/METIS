"""Explicit, bounded age policy for controller-generated run artifacts."""
from __future__ import annotations

import sqlite3
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from metis.core.codex_session import (
    MAX_DERIVED_ARTIFACTS_PER_RUN,
    CodexSession,
    DerivedArtifactLimitError,
)
from metis.core.run_lock import operation_lock, run_lock

MAX_RETENTION_RUNS = 100


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
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
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

    if not apply:
        for (run_id,) in rows:
            result, _outcome = inspect_run(run_id)
            results.append(result)
    else:
        # Hold the whole bounded selection through preflight and apply. The
        # per-run methods reacquire these locks reentrantly.
        run_ids = sorted(str(row[0]) for row in rows)
        preflight: dict[str, tuple[dict[str, Any], dict[str, object] | None]] = {}
        with ExitStack() as stack:
            for run_id in run_ids:
                stack.enter_context(operation_lock(database, run_id))
                stack.enter_context(run_lock(database, run_id))
            for run_id in run_ids:
                preflight[run_id] = inspect_run(run_id)
            if any(result["status"] == "overflow" for result, _ in preflight.values()):
                for run_id in run_ids:
                    result, outcome = preflight[run_id]
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
                        # Locking makes this unreachable for controller writers;
                        # keep fail-closed behavior if an external actor changes DB state.
                        results.append({"run_id": run_id, "status": "overflow",
                                        "artifact_count": exc.count, "artifact_limit": exc.limit})
                    except (ValueError, OSError, sqlite3.Error):
                        results.append({"run_id": run_id, "status": "blocked"})

    return {"applied": apply, "older_than_days": older_than_days,
            "selected_runs": len(rows),
            "artifact_limit_per_run": MAX_DERIVED_ARTIFACTS_PER_RUN,
            "results": results}
