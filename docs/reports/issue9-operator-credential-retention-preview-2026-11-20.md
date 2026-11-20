# Issue #9 operator credential-retention preview (2026-11-20)

The authenticated loopback operator page exposes a preview of the existing
local credential-age policy. The read-only GET route accepts one canonical
`older_than_days` value from 1 through 36,500. The server invokes only the
preview callback and projects a fixed allowlist of aggregate counts; origin
strings, token values, cookie values, cutoff timestamps and arbitrary callback
fields are excluded. Malformed or inconsistent callback results return a
generic unavailable response. The route cannot apply deletion.

The UI clears protected content when the operator token changes, rejects stale
responses after a token or age edit, and uses `textContent` for rendering.
Tests cover authentication, Host/Origin checks, malformed and out-of-range
queries, fixed-field redaction, actual read-only credential and cookie state,
callback-result rejection, and delayed-response invalidation both within and
across views. The CLI integration test confirms the operator server receives
the preview-only callback. Existing retention tests continue to cover the
SQLite WAL sidecar behavior; a WAL-mode read may create or update `-wal` and
`-shm` coordination files.

Observed checks:

- `pytest tests/test_operator_ui.py tests/test_web_credential_retention.py tests/test_cli.py` — passed.
- Ruff on `operator_ui.py`, `cli.py`, `test_operator_ui.py`, and `test_cli.py` — passed.
- mypy on `operator_ui.py` and `cli.py` — passed.
- `scripts/check_repo.py` — passed with zero findings.
- `git diff --check` — passed.

This is an operator visibility increment only. It does not perform deletion,
prove physical erasure, revoke provider credentials, establish backup retention
or encryption, or satisfy Issue #9's P7 dependency. Issue #9 remains open.
