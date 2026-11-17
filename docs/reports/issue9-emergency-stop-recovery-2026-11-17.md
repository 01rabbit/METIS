# Issue #9 local stop/recovery increment

This report records two layers of the P8 emergency-stop gate. The original
deterministic controller-state rehearsal starts a synthetic Codex session,
persists an `EXECUTING` event, requests cancellation, constructs a fresh
controller against the same SQLite database, and runs recovery twice. It
asserts that the session stays `CANCELLED`, the reserved action remains
charged, and no `SOLVED` event is fabricated.

The sandbox now registers its active container in SQLite under the per-run lock
before launch. `metis codex cancel` records cancellation and removes that
container while holding the same lock, then checks `inspect` to distinguish a
confirmed teardown from an `unknown` result. The sandbox runner observes the
terminal cancellation state and does not append `OBSERVING` or `PLANNING` after
the cancellation event. A real-container integration test runs a sleeping
script, cancels it from another thread, checks that the container is absent,
and verifies the run remains `CANCELLED`.

Focused test:

```sh
.venv/bin/python -m pytest -q tests/test_codex_session.py::test_emergency_stop_survives_controller_restart_without_resuming_work
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_cancel_confirms_container_teardown
```

Focused real-container validation (configured image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
`linux/arm64`) passed both the new cancellation test and the existing timeout
process-group teardown test. These tests use a local Docker engine and a
disposable temporary run; they do not exercise host reboot, a separate
controller process, Linux VM deployment, model provider cancellation, or
artifact/secret cleanup. A failed engine response remains `unknown`, not
confirmed. The broader Issue #9 acceptance gate and its P7 dependency remain
open.
