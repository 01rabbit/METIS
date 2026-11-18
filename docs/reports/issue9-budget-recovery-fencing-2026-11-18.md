# Issue #9: action-budget audit and recovery fencing (2026-11-18)

## Scope

`metis audit RUN_ID --database PATH` now includes `codex_budget` when that run
has structured Codex session configuration. It reports configured `max_actions`
and `wall_seconds`, the number of charged `EXECUTING` reservations, and remaining
actions clamped at zero. Non-Codex runs report `codex_budget: null`. The budget
configuration is validated before projection; malformed values fail closed
without echoing their contents. Configuration and events are read in the same
read-only SQLite transaction, without constructing or migrating a Codex session.

Failed tools and reservations interrupted before observation still consume an
action. Operator extensions change the configured limit without deleting prior
charges. The projection omits manifests, verification commitments, event details
and tool output. It remains deterministic for unchanged stored state; it does
not estimate live time remaining, provider charges, or artifact-retention usage.
Session configuration is mutable and outside the event hash chain. `chain_valid`
does not authenticate that configuration or its authorization.

Independent review also identified two recovery defects: an interrupted
artifact's cancelled operation row could remain after recovery and block later
standalone sandbox launches, and recovery between standalone reservation and
worker registration could allow the stale caller to launch after recovery
returned. Standalone sandbox execution now persists a unique operation identity
under the reservation lock, checks it and `EXECUTING` state again under the
launch lock, and verifies it before accepting results. Already-reserved sandbox
calls require the original operation identity; the ZipCrypto artifact path
passes its identity explicitly. A direct ZipCrypto worker invocation instead
reserves and pays for its own standalone sandbox action.

Recovery deletes the revoked operation row only after worker teardown is
confirmed or no worker is registered. An unknown teardown retains the row and
blocks recovery. Per-run operation serialization prevents a new sandbox or
artifact operation from reusing the run while an old caller unwinds; cancellation and recovery do not
take that operation lock. Worker registration uses `INSERT`, so it cannot
silently overwrite another worker record. Revoked callers that never registered
a worker do not issue cleanup commands against the container engine.

## Local validation

```text
.venv/bin/pytest -ra tests/test_ctf_sandbox.py tests/test_codex_session.py \
  tests/test_ctf_zipcrypto.py tests/test_run_audit.py tests/test_cli.py
74 passed, 14 skipped in 20.08s
.venv/bin/ruff check src/metis/core/store.py src/metis/core/ctf_sandbox.py \
  src/metis/core/codex_session.py src/metis/core/ctf_zipcrypto_worker.py \
  tests/test_run_audit.py tests/test_ctf_sandbox.py tests/test_ctf_zipcrypto.py
All checks passed!
.venv/bin/mypy src/metis/core/store.py src/metis/core/ctf_sandbox.py \
  src/metis/core/codex_session.py src/metis/core/ctf_zipcrypto_worker.py
Success: no issues found in 4 source files
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b \
METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra tests/test_ctf_sandbox.py \
  -k 'real_engine_isolation_smoke or real_engine_cancel_confirms_container_teardown or real_engine_cli_cancel_confirms_container_teardown or real_engine_recovery_stops_orphaned_sandbox_before_resuming or real_engine_separate_controller_recovers_orphaned_sandbox or agent_cancel'
6 passed, 21 deselected in 2.85s
```

The deterministic local engine double executes only repository-owned synthetic
fixtures. A thread barrier pauses after a persisted standalone reservation and
before registration. A separate session recovers the run; the stale caller
then returns cancelled without contacting the engine or replacing a newer
registered worker. A fresh sandbox operation succeeds and charges another
action. Additional regressions check that an interrupted artifact row is
cleared on recovery and that an old reserved identity cannot adopt a newer
operation's row. Audit tests cover failed and interrupted reservation charges,
extensions, absent session configuration, malformed limits, private-field
omission, unchanged database bytes and deterministic repeated output.

The combined suite initially skipped real-engine tests because the image
environment variable was unset. A subsequent run against the available pinned
Linux arm64 image passed six real-engine checks: isolation smoke, session and
CLI cancellation, agent cancellation during a long artifact intent, recovery
of an orphaned worker, and separate-controller recovery. Slow exhaustive
search and the unavailable KSNCTF #39 distribution remain skipped.
These results do not establish host-reboot recovery, adversarial container
isolation, provider cost accounting, production retention or release readiness.
Issue #9 and its P7 dependency remain open.

The combined suite above did not set `METIS_TEST_KSNCTF39_ZIP`, so its optional
official-archive seed check was skipped. Afterward, the exact same regression
was run against the official ZIP already stored in METIS run
`0045b063168045c289eaef276dab21c2`:

```text
1 passed in 1.14s
```

This confirms only that the existing seed-recovery regression accepts the
official archive. It does not recover a ZipCrypto key or solve #39.
