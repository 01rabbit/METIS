# Issue #9 user-added artifact purge (2026-11-20)

`metis codex purge-added RUN_ID` previews removal of registered files under
`.metis-added`; deletion requires `--apply`. The shared purge implementation
requires a terminal run with no active operation or worker, checks the manifest
and directory through no-follow file descriptors, rejects symlinks and
unregistered entries, bounds each invocation to 100 deletions, and removes only
`.metis-added` manifest entries. Missing registered files are accepted on
retry, so an interrupted unlink can be completed idempotently. Original
challenge inputs and `.metis-derived` files remain intact. `add-file` now also
refuses to register more than 100 user-added files in one run. Collision
resolution uses exclusive file creation with at most 101 name attempts, and
new generated names remain within the 60-character limit. The purge validator
also accepts safe single-component names up to the filesystem's 255-byte limit
to clean files created by the prior unbounded naming scheme. Add-file opens the
snapshot and destination directories with no-follow directory descriptors, so
a symlink replacement cannot redirect the write outside the run snapshot.

The regression coverage exercises preview/apply, preservation of other artifact
classes, active-run/worker refusal, symlink and unregistered-entry rejection,
interrupted-unlink retry, the per-run bound, and CLI behavior.
It also covers a fully colliding bounded name range, 100 repeated additions of
a maximum-length name followed by preview and applied purge, and cleanup of a
legacy collision name with a 20-digit counter. A symlinked destination
directory is refused without writing into its target.

Legacy `.metis-added` inventories with more than 100 registered files can be
removed in batches of at most 100. Each operation validates the complete
registered directory and is capped at 4,096 legacy entries; larger or
unregistered inventories fail closed for manual handling. Tests cover the
105-file batch path, the unregistered-entry preflight at that size, and the
4,097-registration safety cap without mutation.

Observed checks on the implementation head:

- `uv run --project . --python 3.13 --extra dev python -m pytest -q tests/test_codex_session.py tests/test_cli.py` — passed.
- Ruff on the four changed Python files — passed.
- `uv run --project . --python 3.13 python scripts/check_repo.py` — passed with zero findings.
- `git diff --check` — passed.

This is a manual per-run cleanup command, not age-based automatic retention or
physical erasure from filesystem snapshots/backups. If `add-file` stops after
creating a file but before registering it in the manifest, the purge refuses the
unregistered entry; no automatic orphan recovery is included. This does not
satisfy Issue #9's P7 dependency, host reboot recovery, signed public release,
or complete artifact/credential lifecycle acceptance. Issue #9 remains open.
