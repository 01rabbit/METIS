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

The `test_separate_controller_recovers_orphaned_sandbox_idempotently` test
adds a cross-process crash rehearsal with a deterministic fake engine.
Controller A registers a worker and blocks in `start`; the test sends SIGKILL to
its entire process group, leaving the SQLite row and engine-side container
record behind. A separate Python process first attempts recovery while fake
`rm` is failing and confirms the run remains `EXECUTING`, the worker row stays
registered, and the reserved action remains charged. A later controller
process removes and confirms absence, returns the run to `PLANNING` without a
`SOLVED` event, and deletes the worker row. A third process repeats recovery to
verify idempotency. This exercises the controller-process boundary and
unknown-teardown retry logic; real Docker process-restart behavior is still
covered only by the same-process integration test.

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
.venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_separate_controller_recovers_orphaned_sandbox_idempotently
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_cancel_confirms_container_teardown
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_recovery_stops_orphaned_sandbox_before_resuming
```

Focused real-container validation (configured image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
`linux/arm64`) passed both the new cancellation test and the existing timeout
process-group teardown test. These real-container tests use a local Docker
engine and a disposable temporary run. The separate-process test uses a
deterministic fake engine, not a real daemon restart. The suite does not
exercise host reboot, Linux VM deployment, model provider cancellation, or
artifact/secret cleanup. A failed engine response remains `unknown`, not
confirmed. The broader Issue #9 acceptance gate and its P7 dependency remain
open.

Local validation for the separate-controller fake-engine test:

```text
.venv/bin/pytest -ra tests/test_ctf_sandbox.py::test_separate_controller_recovers_orphaned_sandbox_idempotently
1 passed in 0.86s
```

The additional real-Docker cross-controller test starts a sleeping container
from controller A, verifies it is running, SIGKILLs A's process group, then
uses controller B to confirm teardown and recover the interrupted run. It also
checks that the action budget remains charged, the worker registry row is
removed, no `SOLVED` event appears, and a third recovery is idempotent. Failure
cleanup force-removes the uniquely named temporary container.

Local validation with the pinned `linux/arm64` sandbox image:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra tests/test_ctf_sandbox.py::test_real_engine_separate_controller_recovers_orphaned_sandbox
1 passed in 1.01s
.venv/bin/ruff check tests/test_ctf_sandbox.py
All checks passed!
```

The existing sandbox CI job now runs this test against its freshly built
`linux/amd64` image. This demonstrates controller-process crash recovery with
a real container engine. Host reboot, Linux VM deployment, model provider
cancellation, artifact/secret cleanup, and the P7 benchmark gate remain
uncovered; Issue #9 stays open.

Exact PR HEAD `2950c5097414517c77856d7ed4d3401ebdc1ac85` passed all checks.
The full Python CI suite reported `457 passed, 26 skipped in 86.51s`; the
Docker sandbox integration suite reported `6 passed in 74.92s`. The process
boundary case uses a deterministic fake engine and is included in the Python
suite.
