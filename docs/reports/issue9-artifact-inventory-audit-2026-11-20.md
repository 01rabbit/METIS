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

Duplicate JSON keys at any nesting level, nonstandard JSON constants,
duplicate paths, noncanonical relative paths, traversal, Windows drive/backslash
paths, NULs, Unicode surrogates, and unexpected reserved-directory layouts are
rejected. Derived names must match the existing 32 lowercase hexadecimal digits
and one-to-eight lowercase alphanumeric extension rule. Added registrations
must have exactly one filename component under their reserved directory.

A missing session table, missing manifest column, or absent current-run session
returns `available: false`, never an invented zero. A malformed or oversized
current-run manifest causes the existing CLI failure: exit 2, empty stdout and
the fixed `run audit unavailable or corrupt` message. Other runs' manifests are
not parsed. These limits can make auditing an otherwise usable run unavailable;
the command never silently truncates the registration set.

## Validation

Environment: local macOS arm64, Python 3.12.13; all new fixtures are synthetic.
Commands run from this feature worktree with its `src` selected:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -o addopts='' -q tests/test_run_audit.py tests/test_cli.py tests/test_issue28_evidence.py
86 passed in 13.16s
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest
1558 passed, 36 skipped, 45 subtests passed in 212.48s (0:03:32)
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src tests
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis
Success: no issues found in 112 source files
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_blue_knowledge.py
{"status": "passed", "findings": 0}
git diff --check
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m metis.cli validate challenges/training/fixture-001.json
{"valid": true, "challenge_id": "local-demo-001"}
/Users/mao/Developer/GitHub/METIS/.venv/bin/python -m build --outdir /private/tmp/metis-issue9-artifact-inventory-dist
Successfully built metis_ctf-0.5.0.tar.gz and metis_ctf-0.5.0-py3-none-any.whl
```

Coverage includes classification, zero and exact count/byte/depth limits, the
UTF-8 byte limit on a legacy UTF-16 database,
malformed and oversized input, nested duplicate keys, unexpected paths,
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
fixture used an artifact object instead of the existing `ChallengeManifest`
contract's string list. On unchanged baseline `b027449`, the same command
restricted to that file passed all seven tests in 1.09s. This was caused by the
new validation, not an unrelated baseline failure. The fixture now uses
`[ARCHIVE]`, and a new negative inventory case explicitly retains rejection of
artifact objects. All seven evidence-verifier tests pass in the expanded
focused run above; production validation was not relaxed.
The subsequent full-suite result recorded above passed with that correction.

No CTF input, credential, provider, release, deployment, reboot or purge was
used. Issue #9 remains open for its separate acceptance gates.
