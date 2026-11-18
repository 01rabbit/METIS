# P0 acceptance review — 2026-11-17

## Decision

Accept Issue #1's checklist for the bounded operator-intake and local-fixture
scope. This is not a production security certification, signed-manifest system,
or general-purpose sandbox claim.

## Evidence at the reviewed revision

The exact source revision reviewed for trust boundaries was
`ed924a9d9d78e1473a101e4e23f72230e1986d64`. Its GitHub checks run
`43998590228` and METIS validation run `43998590110` both passed. The run
includes locked dependency installation, full tests, Ruff, mypy, fixture
validation and package build. The sandbox image build and enforced container
tests also passed in the checks run. Local full pytest, Ruff and mypy passed;
Docker-specific local tests may skip when the required image/cgroups are absent.

Contract tests reject false or coerced authorization and grant/challenge ID
mismatch (`tests/test_policy.py`, `tests/test_contracts.py`), plus absolute and
traversal artifact paths (`tests/test_contracts.py`). Descriptor-based artifact
reads reject symlinks, special files and oversize input. `FixtureOracle` checks
that its bounded private answer store is outside solver-visible roots, returns
only a verdict, and is not passed to the provider; tests cover placement,
permissions, exact matching and candidate non-disclosure. The fixed local
container receives no host mounts or network and operates only on bounded
transforms.

An independent AI review at that exact source revision covered scope grant
parsing, artifact intake, oracle separation and candidate/verifier boundaries.
It accepted artifact and oracle handling and identified one trust assumption:
the manifest parser cannot authenticate `granted_by`. The controller's user
initiated URL-intake path creates the manifest itself; untrusted statement and
distribution content do not issue grants. Additional origins require explicit
per-run user grant commands. Direct local manifests are trusted operator input,
not authenticated claims. The `run` path is limited to local fixture transforms
and the separate fixture oracle. These assumptions are now stated in
`docs/adr/0003-lifecycle-evidence.md`.

## Limits retained

The local fixture oracle is not an official CTF verifier. A local manifest has
no cryptographic provenance. The Docker boundary is not proven against kernel
exploits. Production operations, general real-provider security, global model
cost accounting and P1/P8 acceptance remain outside this P0 decision.
