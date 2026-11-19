# Issue #9: age-based derived-artifact retention increment

`metis codex --database STATE.sqlite retention-derived --older-than-days 30`
previews generated `.metis-derived` files for runs whose intake timestamp is at
least 30 days old. `--apply` explicitly invokes the existing per-run
`purge_derived` operation. The selection is ordered and bounded to 100 runs;
an oversized selection fails before deleting anything. The age range is 1 to
3650 days. There is no background deletion.

For every selected run, the existing purge path checks run state, active jobs,
workers and operations under the run locks and checks registered file paths
without following symlinks. A blocked run is reported without stopping other
eligible runs, and an apply with any blocked run exits nonzero. The operation
is retryable: already removed derived files are reconciled with the manifest.
Original inputs and user-added artifacts are excluded.

Each run is capped at 100 registered derived artifacts. Preview reports the
per-run limit and marks an over-limit run `overflow` with its count and limit,
without listing its file paths. Apply holds the selected runs' operation and
state locks, checks the entire bounded batch before deletion, and skips all
runs if any has overflowed; the per-run purge also checks its cap immediately
before filesystem inspection and unlinking.

Review follow-up: terminal eligibility is now an explicit allowlist of
`solved`, `cancelled`, `error`, and `policy_denied`, checked under both run locks
before unlinking. `planning` remains actionable, and `exhausted` can be
resumed with an operator budget extension; neither is eligible even when its
intake timestamp is old. The CLI regression covers old planning and exhausted
runs, nonzero exit on blocked apply, preservation of their generated files,
and an actual extension of the exhausted run. A separate completed old run is
purged in the same test suite while a blocked run remains intact.

Local validation (Python 3.12 virtual environment, synthetic local fixtures):

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -q tests/test_derived_retention.py tests/test_codex_session.py tests/test_cli.py
40 passed
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src/metis/core/derived_retention.py src/metis/core/codex_session.py src/metis/cli.py tests/test_derived_retention.py tests/test_codex_session.py tests/test_cli.py
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis/core/derived_retention.py src/metis/core/codex_session.py src/metis/cli.py
Success: no issues found in 3 source files
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
git diff --check
passed
```

These tests covered preview, age selection, explicit apply, resumable-run
refusal, original-input preservation, idempotent retry, invalid ages,
oversized-selection rejection, the 100-artifact boundary, overflow reporting,
whole-batch no-unlink behavior on overflow, and the existing purge regressions. This does not securely erase filesystem snapshots,
SQLite WAL pages or backups, enforce credential retention, or complete Issue
#9's P7 dependency, host-reboot and signed-release evidence gates.
