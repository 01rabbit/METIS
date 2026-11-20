# Issue #9 user-added artifact purge (2026-11-20)

`metis codex purge-added RUN_ID` previews removal of registered files under
`.metis-added`; deletion requires `--apply`. The shared purge implementation
requires a terminal run with no active operation or worker, checks the manifest
and directory through no-follow file descriptors, rejects symlinks and
unregistered entries, bounds each run to 100 files, and removes only
`.metis-added` manifest entries. Missing registered files are accepted on
retry, so an interrupted unlink can be completed idempotently. Original
challenge inputs and `.metis-derived` files remain intact. `add-file` now also
refuses to register more than 100 user-added files in one run. Collision
resolution uses exclusive file creation with at most 101 name attempts, and
generated names remain within the 60-character purge validation limit.

The regression coverage exercises preview/apply, preservation of other artifact
classes, active-run/worker refusal, symlink and unregistered-entry rejection,
interrupted-unlink retry, the per-run bound, and CLI behavior.
It also covers a fully colliding bounded name range and repeated addition of a
maximum-length filename followed by preview and applied purge.

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
