# Issue #9 queued specialist dispatch pause/resume

## Implemented scope

The loopback operator view now exposes authenticated per-run pause, resume, and
status operations for queued specialist dispatch. The pause state and
pause/resume transition history are stored in SQLite. Repeating the current
state is idempotent and does not append another transition. The status response
contains the current state and most recent 20 transitions, each with an action
and timestamp; it excludes credentials and other free-form fields. Malformed
state or history fails closed with a generic unavailable response.

The scheduler checks the pause state under the run lock before reserving queued
jobs and again immediately before host spawn. If pause wins after reservation,
the job returns to `queued` without a host call or consumed attempt. Resume makes
queued work eligible for ordinary dispatch. Existing running jobs continue, and
run cancellation remains available while paused. The operator UI reloads status
and history when refreshing a selected run and offers an explicit status check.

## Verification performed

Commands run from the feature worktree:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest -o addopts='' -q tests/test_agent_orchestration.py tests/test_operator_ui.py tests/test_cli.py
80 passed in 17.64s

/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src/metis/core/agent_scheduler.py src/metis/core/operator_ui.py src/metis/cli.py tests/test_agent_orchestration.py tests/test_operator_ui.py tests/test_cli.py
All checks passed!

/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis/core/agent_scheduler.py src/metis/core/operator_ui.py src/metis/cli.py
Success: no issues found in 3 source files

PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}

git diff --check
passed
```

## Acceptance boundary

This is a reversible local operator control for queued specialist admission. It
does not stop or interrupt in-flight specialists, prove host-level containment,
or satisfy Issue #9's remaining retention, restart, release, and operational
acceptance gates. The 20-entry limit applies to the exposed history projection;
the SQLite transition log remains local operational state and is not a signed or
tamper-evident audit ledger. No provider/model calls or host reboot were used.
