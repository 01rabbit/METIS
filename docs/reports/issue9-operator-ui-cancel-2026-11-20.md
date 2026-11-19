# Issue #9 operator cancellation API (2026-11-20)

The authenticated loopback operator view now has an exact
`POST /api/runs/{run_id}/cancel` route. The CLI supplies the existing
`CodexSession.cancel` operation, retaining its run lock, cancellation event,
active-operation revocation, and registered-worker teardown behavior. The
route accepts no request body and returns only the run ID, lifecycle status,
and worker-teardown status. Unconfirmed worker teardown is returned as HTTP
202 with status `unknown`; provider, container, event, and token details are
not included in the response or server log. Browser POSTs may send an Origin
header; the handler accepts only the exact bound loopback origin and rejects
foreign origins.

Local synthetic HTTP tests exercised bearer-token and Host/Origin checks,
malformed and unknown run IDs, body rejection, active-run cancellation,
repeat cancellation, read-only audit behavior, and unknown teardown
projection. For the unknown-teardown case, the worker-removal function was a
controlled stand-in; no real container was stopped.

A Playwright smoke test against a disposable local database loaded the served
page, inspected the run audit, and clicked Cancel with a controlled confirmation
dialog. The page displayed `cancelled` and `not_running`. This caught and fixed
the CSP requirement for `connect-src 'self'`; no browser automation artifacts
or test database were retained.

Validation on macOS arm64:

- `PYTHONPATH=/private/tmp/metis-issue9-operator-ui-cancel/src:/private/tmp/metis-issue9-operator-ui-cancel /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest tests/test_operator_ui.py tests/test_codex_session.py tests/test_cli.py` — 40 passed.
- Ruff passed for `operator_ui.py`, `cli.py`, and `test_operator_ui.py`.
- Mypy passed for `operator_ui.py` and `cli.py`.
- `git diff --check` passed.

This validates the local HTTP handler and cancellation projection. It does not
exercise the rendered browser controls, a live worker/container teardown,
host-reboot recovery, credential retention, signed release, or Issue #9's
broader operational acceptance criteria.
