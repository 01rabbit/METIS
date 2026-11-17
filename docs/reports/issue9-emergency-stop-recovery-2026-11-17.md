# Issue #9 local stop/recovery increment

This report records two layers of the P8 emergency-stop gate. The original
deterministic controller-state rehearsal starts a synthetic Codex session,
persists an `EXECUTING` event, requests cancellation, constructs a fresh
controller against the same SQLite database, and runs recovery twice. It
asserts that the session stays `CANCELLED`, the reserved action remains
charged, and no `SOLVED` event is fabricated.

The sandbox now registers its active container in SQLite under the per-run lock
before launch. Both `metis codex cancel` and `recover` remove that container
while holding the same lock, then check `inspect` to distinguish confirmed
teardown from an `unknown` result. Recovery refuses to resume while teardown is
unknown. A late result from the interrupted sandbox is discarded, so it cannot
append an observation after recovery returned the run to `PLANNING`.

Real-container integration tests run a sleeping script, then independently
exercise cancellation and controller recovery. Each confirms the container is
absent and the session does not fabricate a solve. A separate failure-path
test confirms an unknown teardown leaves the session in `EXECUTING` and blocks
recovery.

Sandbox execution cleanup now uses the same delete-and-inspect confirmation for
every resource profile. It removes the SQLite worker row only after absence is
confirmed. If removal/inspection is unknown, it raises while preserving the row
and leaves the run `EXECUTING`; a later recovery retries teardown. The
`test_sandbox_cleanup_failure_keeps_worker_registered_until_recovery` regression
injects an unknown cleanup, verifies the row and state remain, then restores
the engine check and confirms recovery removes the container and row before
returning to planning.

Focused test:

```sh
.venv/bin/python -m pytest -q tests/test_codex_session.py::test_emergency_stop_survives_controller_restart_without_resuming_work
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_cancel_confirms_container_teardown
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_recovery_stops_orphaned_sandbox_before_resuming
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
