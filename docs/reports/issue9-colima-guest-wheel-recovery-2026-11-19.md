# Issue #9: wheel installation and controller recovery inside Colima

On 2026-11-19, an Apple Silicon Mac ran a new, disposable Colima 0.10.3 VZ
profile with Docker and host directory mounts disabled. The guest reported
Ubuntu 24.04.4 LTS, Linux `6.8.0-117-generic` on `aarch64`, Python 3.12.3,
and Docker 29.5.2. The METIS controller and recovery CLI both ran inside
the guest from the installed wheel.

## Installation

Built `metis_ctf-0.5.0-py3-none-any.whl` with uv 0.13.5 at source commit
`f59387899a9f53847cefe9c9dc9c8822967c805a`. Its SHA-256 was
`c4154cf9a55221e3aba203257a8138f5ae3f94c3c5b2cfb220e35b52415ce771`
on the host and again after transfer into the guest. The guest received the
wheel, lockfile exports, and the standalone test module over Colima SSH.
It received no repository checkout or credentials. `python3.12-venv` was
installed from Ubuntu's repositories because the guest initially lacked
`ensurepip`.

With `PYTHONPATH` and `PYTHONHOME` unset, the guest downloaded binary
dependencies with `pip download --require-hashes --only-binary=:all:`.
A new Python 3.12 venv installed the hashed dependencies from its local
wheelhouse with `--no-index` and installed the candidate wheel with
`--no-index --no-deps`. `pip check` reported no broken requirements,
`metis --version` reported `METIS 0.5.0`, `metis doctor` reported `ready: true`,
and `metis.__file__` resolved inside the venv. Lockfile-exported development
dependencies were installed afterward for the recovery test.

## Controller recovery

Built `sandbox/Dockerfile` on the disposable Docker daemon for `linux/arm64`.
The immutable local image ID was
`sha256:5600921e313b00f0c43587b5173a337467916590ebe012e41ee0bb2ae6669997`.
With this ID set as `METIS_TEST_SANDBOX_IMAGE`, the guest ran the existing
synthetic test from the directory holding the transferred test file:

```sh
installed/bin/python -I -m pytest -q --basetemp replay-state \
  test_ctf_sandbox.py::test_real_engine_separate_controller_recovers_orphaned_sandbox
```

The result was `1 passed in 0.99s`. The test confirmed that the sleeping
worker stayed alive after controller A was killed. Controller B recovered
the run to `planning`, confirmed teardown, and preserved the charged action.
A second recovery returned `not_running`, and the audit chain had no `solved`
event. A post-test check found 79 of 80 actions remaining, zero worker and
active-operation rows, and no containers on the disposable daemon.

The disposable Colima profile was stopped and deleted. Colima left its
unused Lima disk, which was deleted separately. The profile, disk, and
Docker context were then absent. The existing `default` and `rosetta`
profiles stayed stopped, and the selected Docker context remained `default`.

This run covers guest-native installation from a candidate wheel and recovery
after controller termination. Provisioning and image building accessed package
repositories. The sandbox build inputs and wheel build backend were not fully
pinned. The run did not exercise VM or host reboot, a signed installer or
release, provider or model calls, real challenge inputs, retention or secure
storage, or the P7 benchmark gate. Issue #9 remains open.
