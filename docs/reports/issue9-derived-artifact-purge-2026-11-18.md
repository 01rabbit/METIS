# Issue #9: per-run derived-artifact purge (2026-11-18)

## Scope

Added `metis codex purge-derived RUN_ID`, which previews registered files under
that run's `.metis-derived` directory. Deletion requires `--apply`. Original
challenge inputs and user-added `.metis-added` files are outside the purge
scope.

The controller takes the per-run operation and state locks, rejects active
run states, active operations, registered sandbox workers, and queued/running
agent jobs, and opens the snapshot and derived directory without following
symlinks. It rejects unregistered directory entries, unexpected registered
paths, non-regular files, and files with multiple hard links. It unlinks
registered generated files before removing their manifest entries. A retry
can finish a partially completed purge when a registered file is already
missing; if manifest storage fails after unlink, the manifest remains
recoverable on the next invocation. `enqueue` and `retry` now serialize under
the same per-run lock. Global dispatch locks selected runs during queued-to-
running reservation and limits its reservation query to that locked set; once
the lock is released, the job is already marked running and purge refuses it.
Independent review caught the initial queue race; after this correction, the
reviewer confirmed that enqueue, retry, and dispatch no longer cross the purge
exclusion check.

## Local validation

```text
.venv/bin/pytest -ra \
  tests/test_codex_session.py::test_purge_derived_keeps_original_and_user_added_artifacts \
  tests/test_codex_session.py::test_purge_derived_refuses_active_runs_and_registered_workers \
  tests/test_codex_session.py::test_purge_derived_rejects_symlink_and_preserves_external_target \
  tests/test_codex_session.py::test_purge_derived_recovers_after_file_unlink_before_manifest_update \
  tests/test_codex_session.py::test_purge_derived_rejects_unregistered_directory_entries \
  tests/test_cli.py::test_cli_purge_derived_defaults_to_preview_and_apply_is_explicit
6 passed
.venv/bin/ruff check src/metis/core/codex_session.py src/metis/cli.py \
  tests/test_codex_session.py tests/test_cli.py
All checks passed!
.venv/bin/mypy src/metis/core/codex_session.py src/metis/cli.py
Success: no issues found in 2 source files
.venv/bin/pytest -ra tests/test_agent_orchestration.py::test_scheduler_queue_mutations_wait_for_run_lock
3 passed
.venv/bin/ruff check src/metis/core/agent_scheduler.py tests/test_agent_orchestration.py
All checks passed!
.venv/bin/mypy src/metis/core/agent_scheduler.py
Success: no issues found in 1 source file
.venv/bin/pytest -ra tests/test_agent_orchestration.py tests/test_codex_session.py \
  tests/test_cli.py tests/test_issue6_benchmark_analysis.py
58 passed in 6.23s
.venv/bin/ruff check src/metis/core/agent_scheduler.py src/metis/core/codex_session.py \
  src/metis/core/store.py src/metis/cli.py src/metis/evaluation \
  tests/test_agent_orchestration.py tests/test_codex_session.py tests/test_cli.py \
  tests/test_issue6_benchmark_analysis.py
All checks passed!
.venv/bin/mypy src/metis/core/agent_scheduler.py src/metis/core/codex_session.py \
  src/metis/core/store.py src/metis/cli.py src/metis/evaluation
Success: no issues found in 6 source files
```

The focused tests confirm preview leaves the manifest and generated file
untouched; apply removes only the registered derived artifact and its manifest
entry; original and user-added inputs remain; repeated apply is idempotent;
active runs, a registered sandbox worker, and a queued agent job are refused; a
symlink cannot redirect deletion outside the snapshot; unregistered files are
left alone and make the purge fail closed; and an already-missing file is
reconciled after a simulated interruption.

## Limits

This removes directory entries; it does not establish secure erasure from
filesystem snapshots, SQLite WAL pages, backups, or storage media. It covers
only registered `.metis-derived` files and does not implement retention policy,
credential lifecycle controls, or a full artifact inventory. The preview does
not delete run files or update the manifest; CLI session initialization may
still create or migrate local SQLite schema, so it is not a byte-level
read-only operation. Issue #9 remains open for its P7 dependency, host reboot
and signed release evidence, and the remaining production-operation gates.
