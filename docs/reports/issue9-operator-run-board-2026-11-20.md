# Issue #9 bounded operator run board (2026-11-20)

The local operator API now exposes `GET /api/runs?limit=N`. It accepts an
integer limit from 1 through 100, selects newest runs by their latest event
timestamp, and validates each selected event chain in the same read-only
SQLite snapshot. If any selected chain is corrupt, the list fails closed.
Run discovery uses a timestamp index and scans at most 4,096 index entries
and 5 MiB of keys per request. Index keys over 512 bytes fail closed, with a
4 KiB SQLite value limit during discovery. Selected chains are separately
capped at 20,000 total events and 8 MiB across all stored event fields. The
list connection's SQLite value limit is 256 KiB, so a legacy oversized field
fails closed before it can be materialized. Writable store initialization and
operator server startup create the index, so existing databases are migrated
once before the read-only list endpoint begins serving requests.

The response is an allowlisted projection containing only the run ID, current
status, last event timestamp, and configured action/time budget. The browser
loads the newest 20, supports selecting a run, and uses the existing audit and
cancel operations. Non-hex run identifiers remain available to the lower-level
audit API but are omitted from the browser list because the operator routes
require canonical 32-character hex IDs.

Operator tokens are restricted to visible ASCII, and non-ASCII Authorization
headers fail as unauthorized instead of raising during constant-time
comparison.

Validation on macOS arm64:

- `PYTHONPATH=/private/tmp/metis-issue9-operator-run-board/src:/private/tmp/metis-issue9-operator-run-board /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest tests/test_run_audit.py tests/test_operator_ui.py` — 43 passed.
- Ruff, mypy, `scripts/check_repo.py`, and `git diff --check` passed.
- Playwright against a disposable local SQLite database loaded two synthetic
  runs, selected the newest, and displayed its audit summary with a valid
  chain. No real worker was started or stopped.
- The temporary database and Playwright artifacts were removed after the
  browser check.

This is a bounded monitoring increment only. It does not satisfy Issue #9's
host-reboot, secure-retention, release, or Issue #8 benchmark dependencies.
