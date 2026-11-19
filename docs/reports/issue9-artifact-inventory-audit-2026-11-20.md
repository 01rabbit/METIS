# Issue #9: read-only artifact registration inventory

## Scope and interpretation

`metis audit RUN_ID --database PATH` includes
`operational_state.artifact_inventory` from the current run's stored manifest,
inside the same SQLite read transaction as event-chain validation. It reports:

- `registered_artifacts`: the number of unique registered paths;
- `registered_derived`: registrations under `.metis-derived/` with the existing
  generated-name format;
- `registered_added`: registrations under `.metis-added/`;
- `registered_other`: registrations outside those two reserved directories;
- `filesystem_verified: false`.

These are mutable registration counts. Prefix classification does not
authenticate a file's origin. The audit does not read the artifact root, open
or inspect artifact files, or return manifest fields, filenames, paths, hashes,
or contents. Missing files still count as registrations. A zero count does not
establish that no files remain. Counts do not establish existence, size, erasure,
retention-policy compliance, or whether a purge would be safe.

The projection does not construct `CodexSession`, initialize schemas, acquire
METIS run/operation locks, or call the retention or purge implementations. The
existing deletion controls and their separate filesystem/worker checks retain
their scope. The CLI opens SQLite in read-only mode; SQLite's normal WAL/SHM
handling remains separate from METIS lock creation.

## Input bounds and failure behavior

SQLite checks the manifest's type and database-encoded byte length before
returning it to Python: text only, at most 1,048,576 stored bytes. A second
1,048,576-byte UTF-8 check also covers legacy UTF-16 databases. JSON nesting is limited to
64 before decoding, and the strict artifact list allows at most 4,096 strings.
Other manifest fields are ignored after bounded JSON decoding; this is not
full challenge-manifest or authorization validation.

The inventory does not publish counts for duplicate JSON keys at any nesting level, nonstandard JSON constants,
duplicate paths, noncanonical relative paths, traversal, Windows drive/backslash
paths, NULs, Unicode surrogates, or unrecognized reserved-directory layouts.
Recognized derived names match the existing 32 lowercase hexadecimal digits
and one-to-eight lowercase alphanumeric extension rule. Added registrations
are recognized only with one filename component under their reserved directory.

A missing session table, missing manifest column, absent current-run session,
malformed/oversized manifest, text decoding failure or unrecognized layout
returns only `artifact_inventory: {available: false}`, never an invented zero
or partial counts. The event chain, budget and other operational counters still
appear in the audit, and the CLI succeeds if the rest of the audit is valid.
Other runs' manifests are not parsed. Event-chain corruption still fails the
audit through its existing error handling.

A SQLite error makes inventory unavailable only while `db.in_transaction`
remains true. If SQLite has ended the read transaction, the error is re-raised
and the whole audit fails through its existing safe CLI error handling. Later
counters are never read after that lost-transaction outcome, so the audit cannot
silently combine the earlier validated chain with a new SQLite snapshot.

These recognition rules are narrower than the persistence contract and do not
replace or tighten `ChallengeManifest.check_grant`. Existing valid shapes such
as `./a.bin`, `a/./b`, `dir/`, duplicate path entries, nested `.metis-added`
paths and nongenerated `.metis-derived/x.bin` paths retain a valid full audit
with inventory unavailable. The inventory never normalizes those paths,
silently removes duplicates or infers a partial count.

## Validation

Environment: local macOS arm64, Python 3.12.13; all new fixtures are synthetic.
Commands run from this feature worktree with its `src` selected:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -o addopts='' -q tests/test_run_audit.py tests/test_cli.py tests/test_issue28_evidence.py
95 passed in 14.39s
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src tests
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis
Success: no issues found in 112 source files
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_blue_knowledge.py
{"status": "passed", "findings": 0}
git diff --check
```

The final change only guards the SQLite error fallback and expands its focused
regressions. The latest head `41da49916fe5c4419cc33e0a5b341354df8c7b05`
also completed the full suite successfully. The repository's quiet pytest
configuration suppressed the pass/skip summary; a separate collection run
reported 1,603 tests. No pass/skip breakdown is claimed for this run.

```text
PYTHONPATH=src:. /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest -q
exit code 0
PYTHONPATH=src:. /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest --collect-only -q
1,603 collected tests
```

The preceding head `2d0dd30540de025b23a3d395408c4769daeeefb8`, before the
transaction guard, had this recorded full-suite result:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest
1565 passed, 36 skipped, 45 subtests passed in 220.13s (0:03:40)
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m metis.cli validate challenges/training/fixture-001.json
{"valid": true, "challenge_id": "local-demo-001"}
/Users/mao/Developer/GitHub/METIS/.venv/bin/python -m build --outdir /private/tmp/metis-issue9-artifact-inventory-dist
Successfully built metis_ctf-0.5.0.tar.gz and metis_ctf-0.5.0-py3-none-any.whl
```

Coverage includes classification, zero and exact count/byte/depth limits, the
UTF-8 byte limit on a legacy UTF-16 database,
malformed and oversized input, nested duplicate keys, unrecognized paths,
other-run isolation, legacy schema, private sentinels, unchanged database bytes,
schema, logical dump and artifact tree, and no new lock paths. The direct audit
test denies file opens, directory listing/scanning, non-database stats, session
construction and run/operation lock acquisition. A concurrent writer changes
the manifest after event-chain reading; the audit retains the original
registration count until its next transaction.

During development, a deep ignored JSON value was initially accepted; the
64-level preflight and quoted-bracket/escape boundary regression address that
case. A test guard initially denied SQLite-path resolution's own database stat;
the guard now permits that database stat while rejecting non-database stats.

The first full-suite run reported `3 failed, 1554 passed, 36 skipped, 45
subtests passed in 225.41s`. All failures were in
`tests/test_issue28_evidence.py`: `test_synthetic_evidence_passes`,
`test_rejects_incomplete_scan`, and
`test_rejects_incomplete_audited_scan_with_valid_chain`. Its handcrafted
fixture used an artifact object. On unchanged baseline `b027449`, the same command
restricted to that file passed all seven tests in 1.09s. This was caused by the
new optional inventory validation, not an unrelated baseline failure. An initial
fixture normalization let the first full rerun pass but did not address the
broader compatibility problem identified in independent review: valid persisted
paths can be outside the inventory's recognition rules. The original Issue #28
fixture has now been restored. Inventory failures are isolated to its
`available: false` result, including malformed manifests and those existing
valid shapes. Regression tests validate the six representative shapes through
`ChallengeManifest` first and then assert intact event-chain, budget and job
counts through both the API and CLI. A SQLite text-decoding failure likewise
leaves the full audit available, including a later job count. Further independent
review identified that a broad SQLite error fallback could mask automatic
transaction rollback. The final guard re-raises if the transaction is no longer
active. Synthetic connection faults cover both outcomes: a surviving transaction
retains chain, budget and later job counts; a rolled-back transaction raises
without reading any later job counters. No persistence validation or
artifact-access authority was changed.

No CTF input, credential, provider, release, deployment, reboot or purge was
used. Issue #9 remains open for its separate acceptance gates.
