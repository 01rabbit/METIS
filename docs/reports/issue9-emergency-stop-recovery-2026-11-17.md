# Issue #9 local stop/recovery increment

This is a deterministic controller-state rehearsal for one slice of the P8
operator recovery gate. It starts a synthetic Codex session, persists an
`EXECUTING` event, requests cancellation, constructs a fresh controller against
the same SQLite database, and runs recovery twice. The regression asserts that
the session stays `CANCELLED`, the reserved action remains charged, and no
`SOLVED` event is fabricated.

Focused test:

```sh
.venv/bin/python -m pytest -q tests/test_codex_session.py::test_emergency_stop_survives_controller_restart_without_resuming_work
```

This fixture exercises SQLite lifecycle persistence only. It has no live
subprocess, Docker worker, Linux VM, model provider, or external target, so it
does not demonstrate process-tree termination, host reboot recovery, macOS to
Linux deployment, or artifact/secret cleanup. A real worker stop must be
confirmed by its execution host before retry or release; `unknown` must remain
operator-visible. The broader Issue #9 acceptance gate and its P7 dependency
remain open.
