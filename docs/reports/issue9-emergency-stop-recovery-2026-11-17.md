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
deterministic fake engine, not a real daemon restart. At this stage the suite
did not exercise host reboot, Linux VM deployment, model provider cancellation,
or artifact/secret cleanup. A failed engine response remains `unknown`, not
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

Exact PR HEAD `e33d070b042238eb7b8ceb9f1bb7dcb5977fcb52` passed the Docker
sandbox job with all seven selected integration tests (`7 passed in 120.72s`).
The same head passed the Python suite (`459 passed, 27 skipped in 86.57s`),
aarch64 seccomp, Ruff, mypy, fixture validation, and package build.

The existing sandbox CI job now runs this test against its freshly built
`linux/amd64` image. This demonstrates controller-process crash recovery with
a real container engine. Host reboot, model provider cancellation,
artifact/secret cleanup, and the P7 benchmark gate remain uncovered; Issue #9
stays open.

Exact PR HEAD `2950c5097414517c77856d7ed4d3401ebdc1ac85` passed all checks.
The full Python CI suite reported `457 passed, 26 skipped in 86.51s`; the
Docker sandbox integration suite reported `6 passed in 74.92s`. The process
boundary case uses a deterministic fake engine and is included in the Python
suite.

## 2026-11-17 macOS controller and Linux VM smoke

This workspace is Apple Silicon macOS (`arm64`). The active Docker context was
`colima-rosetta`, backed by Colima 0.10.3 and Docker Engine 29.5.2 on Ubuntu
24.04.4 LTS/aarch64 (kernel 6.8.0-117-generic). The Mac controller invoked the
real container engine through that Linux VM.

Built the sandbox image from the repository Dockerfile for `linux/arm64`:

```text
docker build --platform linux/arm64 --tag metis-issue9-smoke:2026-11-17 sandbox
image ID: sha256:a88e7bdbf35049393a02f4246da183e4bb450b2428570c16201a60590b9ba521
```

Then ran the existing cross-controller recovery test against that exact image:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:a88e7bdbf35049393a02f4246da183e4bb450b2428570c16201a60590b9ba521 METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -vv -s tests/test_ctf_sandbox.py::test_real_engine_separate_controller_recovers_orphaned_sandbox
1 passed in 0.68s
```

Controller A ran on macOS and launched the sleeping sandbox in the Linux VM;
after A was SIGKILLed, controller B stopped the container and recovered the
SQLite run. The test verified the action remained charged, no solve event was
created, and a third recovery was idempotent. This is an end-to-end smoke of
the native Mac controller to the isolated Linux VM execution engine. This
specific test did not cover VM reboot, clean-machine installation, VM
provisioning, or production monitoring and retention; later checks in this
report add fresh-profile and VM-restart evidence.

## 2026-11-17 clean wheel installation and E2E smoke

Built the project wheel on the Mac and exported runtime dependencies from the
checked-in lockfile. A newly created Python 3.12 virtual environment was
populated from that export, then the wheel itself was installed without
dependencies; the repository source was not installed editable. The local uv
version was 0.11.32. Wheel SHA-256:
`ef5f0a0453bb91adf58a20d3dc9e45c77c9578dda6defb90ce28d5ab39457e11`.

Commands and observed results:

```text
uv build --wheel --out-dir /tmp/metis-p8-smoke.kSwTJn/dist
Successfully built metis_ctf-0.5.0-py3-none-any.whl
uv export --locked --no-dev --no-emit-project --output-file /tmp/metis-p8-smoke.kSwTJn/requirements.txt
Resolved 65 packages
uv venv --python python3.12 /tmp/metis-p8-smoke.kSwTJn/venv
uv pip sync --python /tmp/metis-p8-smoke.kSwTJn/venv/bin/python /tmp/metis-p8-smoke.kSwTJn/requirements.txt
Installed 16 pinned runtime packages
uv pip install --python /tmp/metis-p8-smoke.kSwTJn/venv/bin/python --no-deps /tmp/metis-p8-smoke.kSwTJn/dist/metis_ctf-0.5.0-py3-none-any.whl
Installed metis-ctf==0.5.0
/tmp/metis-p8-smoke.kSwTJn/venv/bin/metis --version
METIS 0.5.0
/tmp/metis-p8-smoke.kSwTJn/venv/bin/metis validate challenges/training/fixture-001.json
{"valid": true, "challenge_id": "local-demo-001"}
```

The installed-wheel Python API created a temporary, explicitly authorized
synthetic run using `/tmp/metis-p8-smoke.kSwTJn/hello.py`; the run id was
`694364977d5244348ef03cf7776f3c7e`. The installed CLI configured the existing
immutable `linux/arm64` image and ran the declared script through the active
Colima Linux VM:

```text
/tmp/metis-p8-smoke.kSwTJn/venv/bin/metis sandbox --database /tmp/metis-p8-smoke.kSwTJn/runs/e2e.sqlite configure --engine docker --image sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b --platform linux/arm64
/tmp/metis-p8-smoke.kSwTJn/venv/bin/metis sandbox --database /tmp/metis-p8-smoke.kSwTJn/runs/e2e.sqlite run 694364977d5244348ef03cf7776f3c7e 00-hello.py --mode script --script /tmp/metis-p8-smoke.kSwTJn/hello.py --timeout 10
{"ok": true, "exit_code": 0, "stdout": "hello from clean wheel install\\n"}
```

The script returned `hello from clean wheel install` with exit code 0 in
0.006s. A policy probe through the same installed CLI returned `net-blocked`,
`rootfs-readonly`, and uid `65534`. Both observations were stored as hashes and
exit metadata by the run ledger.

This first pass provides a reproducible local wheel install and a native
Mac-controller to Linux-VM smoke with boundary probes. The fresh profile and
VM-restart checks below add separate evidence. This does not establish a signed
installer, host reboot recovery, secret rotation/retention, or a P7 benchmark
regression gate. Issue #9 remains open.

## 2026-11-17 fresh VM provisioning and reboot recovery

Created a separate Colima profile `metis-p8-fresh` with Colima 0.10.3,
Virtualization.Framework, two CPUs, four GiB RAM, and a new 20 GiB root disk.
The guest reported Ubuntu 24.04.4 LTS, aarch64, kernel
`6.8.0-117-generic`. Its Docker daemon was 29.5.2. The active `colima-rosetta`
context was left unchanged. Built the repository sandbox image from a fresh
Debian Bookworm base on this guest; immutable image ID:
`sha256:97571cce9372893ed98631c1fe08316c7b2446e10e1042d61df16cb07c7d8dfa`
(`linux/arm64`).

Commands:

```text
colima start metis-p8-fresh --cpu 2 --memory 4 --disk 40 --vm-type vz --runtime docker --activate=false --save-config=true
docker --context colima-metis-p8-fresh build --platform linux/arm64 --tag metis-p8-fresh:2026-11-17 sandbox
docker --context colima-metis-p8-fresh image inspect metis-p8-fresh:2026-11-17 --format '{{.Id}} {{.Os}}/{{.Architecture}}'
sha256:97571cce9372893ed98631c1fe08316c7b2446e10e1042d61df16cb07c7d8dfa linux/arm64
```

The already-built METIS wheel (`ef5f0a…39457e11`) in the fresh Python 3.12
environment configured this image and ran the same harmless script through
`DOCKER_HOST=unix:///Users/mao/.colima/metis-p8-fresh/docker.sock`. It exited
0 in 0.004s with `hello from clean wheel install`. A second run through this
newly built image reported `net-blocked`, `rootfs-readonly`, uid `65534`, and
`network:none` with no host mounts.

Then exercised an interrupted run across a VM stop/start cycle. Controller A
started a sleeping sandbox on the fresh profile; after A was SIGKILLed, the
VM was stopped and restarted. Controller B recovered the persisted run and
confirmed the worker container was absent. The run returned to `planning`,
kept its one charged action (`9` remaining), and had no solve event. A rerun of
the harness, including cleanup, exited 0. Run
`35706202465b4391a1d39023391d1f0b`; worker
`metis-sandbox-6acdfc8161e84104`.

The cross-controller Docker test also passed on this fresh profile:

```text
DOCKER_HOST=unix:///Users/mao/.colima/metis-p8-fresh/docker.sock METIS_TEST_SANDBOX_IMAGE=sha256:97571cce9372893ed98631c1fe08316c7b2446e10e1042d61df16cb07c7d8dfa METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/python -m pytest -q tests/test_ctf_sandbox.py::test_real_engine_separate_controller_recovers_orphaned_sandbox
1 passed
```

This is VM stop/start recovery, not a macOS host reboot test. The sandbox image
was built from current Debian and Python package repositories rather than a
fully version-pinned image recipe; it is not a signed release installer. Host
reboot, credential revocation/retention, secure secret storage, production
monitoring, and the P7 benchmark regression gate remain uncovered. Issue #9
stays open.

## 2026-11-17 local credential replacement check

A new local test calls `WebWorkflow.auth` twice for one synthetic platform
origin, then confirms the next request uses the replacement Bearer credential
and the old fixture value is absent from the stored payload. The focused test
passed (`1 passed`); Ruff and mypy also passed. This proves the existing
per-origin upsert replacement behavior in a local test, not revocation,
retention limits, encrypted-at-rest storage, provider-side credential
rotation, or production lifecycle controls. Issue #9 remains open.

## Operator recovery procedure for the verified controller-to-VM path

Use the same persistent METIS database and the same configured Docker endpoint
that launched the run. The tested setup was a macOS controller using a Colima
Linux VM; this procedure does not claim support for host reboot or a production
installer.

1. Check the run and engine before intervening:

   ```sh
   .venv/bin/metis inspect --database "$METIS_DB" "$RUN_ID"
   .venv/bin/metis sandbox --database "$METIS_DB" status
   ```

2. If the controller is still alive and the run needs to stop, request
   cancellation. If the controller died while a sandbox was active, recover
   from another controller using the same database and Docker endpoint:

   ```sh
   .venv/bin/metis codex --database "$METIS_DB" cancel "$RUN_ID"
   .venv/bin/metis codex --database "$METIS_DB" recover "$RUN_ID"
   ```

   Run `cancel` only for the live-run case and `recover` for an interrupted
   controller; `recover` performs removal and absence confirmation itself.

3. Read the run again and check its board entry:

   ```sh
   .venv/bin/metis inspect --database "$METIS_DB" "$RUN_ID"
   .venv/bin/metis codex --database "$METIS_DB" board
   ```

   In the verified recovery case, the run returns to planning, the interrupted
   action remains charged, and no solve event is created. A canceled session
   remains canceled. If teardown or absence cannot be confirmed, recovery
   fails closed and leaves the run executing with its worker record retained;
   keep the database intact and retry after the engine is available. Do not
   manually mark the run solved or delete the worker record.

The underlying lifecycle behavior is exercised by the recorded real Docker
controller-crash and VM stop/start tests. The exact CLI sequence above has not
been rehearsed manually end to end. These tests do not establish a monitoring
dashboard, a macOS host reboot procedure, or production support.
