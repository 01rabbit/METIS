# Issue #9 unified read-only operational audit (2026-11-18)

## Scope

`metis audit RUN_ID --database PATH` now returns a count-only operational
snapshot alongside the validated event-chain summary. Optional subsystems are
reported as unavailable when their tables are absent; they are not represented
as empty. The command does not initialize a scheduler, session, or sandbox and
does not create tables.

The snapshot includes:

- agent job counts for known states and a bounded `other` count, including
  `unknown` explicitly;
- outstanding mediated action reservations;
- configured, reserved, and remaining controller model-turn attempts;
- registered active-operation and sandbox-worker rows;
- pending private-candidate count.

It never returns job IDs, failure text, tool identities, container names,
candidate values, paths, or digests. Every query is scoped to the requested run
and uses the same SQLite read transaction as event-chain validation.

## Interpretation limits

Operational counters are mutable database state and are not covered by the
event hash chain. A model-turn reservation is a controller reservation, not
provider-confirmed use. A registered sandbox worker row does not prove the
process or container is still live. The audit does not report token cost,
provider usage, artifact retention, credential storage, or provider-side token
revocation. It does not meet Issue #9's host-reboot or release-publication
gates.

## Validation

```text
.venv/bin/pytest -q tests/test_run_audit.py
15 passed
.venv/bin/ruff check src/metis/core/store.py tests/test_run_audit.py
All checks passed!
.venv/bin/mypy src/metis/core/store.py
Success: no issues found in 1 source file
git diff --check
```

Coverage includes mixed job states, unknown state normalization, other-run
exclusion, outstanding reservations, privacy omissions, read-only deterministic
output, unavailable optional tables, inconsistent/orphaned/partial-schema
model-turn accounting, and a concurrent writer demonstrating that operational
counters share the event-chain snapshot.

Issue #9 remains open; this improves local operator visibility but does not
replace its P7, host-reboot, signed-release, retention, secure-storage, and
provider-revocation acceptance evidence.
