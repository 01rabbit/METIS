# Issue #9: read-only per-run audit summary (2026-11-18)

## Scope

Added `metis audit RUN_ID --database PATH`, a deterministic JSON projection over
one run's validated event chain. It reports lifecycle status, event count and
sequence bounds, first/last event timestamps, status counts, chain validity,
and the terminal chain digest. It intentionally omits event details, including
free-form text that could contain prompts, outputs, credentials, or candidates.

The command opens the existing SQLite database in read-only mode, validates
the event chain in a single read snapshot, and does not create a missing
database. A missing run or corrupt chain fails closed with exit status 2. The
existing `metis inspect` JSONL export is unchanged.

## Local validation

```text
.venv/bin/pytest -ra tests/test_cli.py
11 passed
.venv/bin/ruff check src/metis/core/store.py src/metis/cli.py tests/test_cli.py
All checks passed!
.venv/bin/mypy src/metis/core/store.py src/metis/cli.py
Success: no issues found in 2 source files
```

The CLI acceptance tests verify deterministic lifecycle counts, omission of a
synthetic private detail value, unchanged database bytes on successful and
corrupt-chain reads, and failure without creating a missing database. The
corrupt-chain case modifies its disposable test database after dropping its
append-only trigger; the audit command itself remains read-only.

## Limits

This is a local read-only audit projection, not a unified operator UI, a
tamper-proof ledger against the database owner, or an independent signature.
`chain_valid` means the stored sequence, payload hashes, and event identities
are consistent; it does not authenticate provenance or independently verify
the semantic validity of every state transition.
The current event schema does not provide reliable structured cost, provider
usage, artifact-retention, or complete action-budget counters, so the command
does not infer or report those values. Issue #9 remains open for its P7
dependency, host reboot, signed release provenance, artifact and credential
retention, secure storage, and provider-side revocation evidence.
