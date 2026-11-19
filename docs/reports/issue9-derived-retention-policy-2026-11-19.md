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

Local validation (Python 3.12 virtual environment, synthetic local fixtures):

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -q tests/test_derived_retention.py tests/test_codex_session.py tests/test_cli.py
37 passed
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src/metis/core/derived_retention.py src/metis/cli.py tests/test_derived_retention.py
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis/core/derived_retention.py src/metis/cli.py
Success: no issues found in 2 source files
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
git diff --check
passed
```

These tests covered preview, age selection, explicit apply, active-run
refusal, original-input preservation, idempotent retry, invalid ages,
oversized-selection rejection, and the existing purge regressions. This does not securely erase filesystem snapshots,
SQLite WAL pages or backups, enforce credential retention, or complete Issue
#9's P7 dependency, host-reboot and signed-release evidence gates.
