# Issue #7: per-run capability review gate (2026-11-17)

## Decision

Implement one review-gated, fixed built-in transform, `rot13_decode`, as a
narrow P6 increment. We reviewed two expert recommendations. One favored
limiting capability additions to reviewed repository changes and leaving
proposals inert. The other proposed an explicit, digest-bound, per-run operator
approval for already implemented built-ins. We adopted the latter only for
this one built-in: no arbitrary code or runtime plugin registry is accepted,
and new implementations still require a reviewed METIS code change.

## Behavior and boundaries

- `rot13_decode` is denied from workflow candidates unless the selected run has
  an active approval row for the exact versioned descriptor digest.
- `metis workflow approve` and `revoke` require typing the exact operation,
  capability, version, descriptor digest, and run ID. The full descriptor and
  limits are shown before confirmation; a second code audit found that the
  original name-only phrase was insufficient, so the gate was tightened and a
  stale-version CLI confirmation test was added. EOF, mismatch, changed
  descriptor, unknown capability, or missing run fails closed. `status` shows
  the active capability set and append-only review history.
- Approval is per-run, revocable, and invalidated when the descriptor version
  or implementation digest changes. It does not modify `ARTIFACT_TOOLS`.
- The controller validates before sandbox launch; the fixed sandbox runner has
  a second allowlist and enforces the same existing input/output bounds.
- Policy and private digest verifier are unchanged. Output remains untrusted.
- The local OS username is recorded as supplied by `getpass`; this is not a
  cryptographic identity or protection from the local database owner.

## Validation

Environment: METIS's configured immutable Docker image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
`linux/arm64`, network disabled, no host mounts. Command:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra tests/test_ctf_workflow.py tests/test_cli.py
20 passed in 2.30s
.venv/bin/ruff check src/metis/core/ctf_workflow.py src/metis/cli.py tests/test_ctf_workflow.py tests/test_cli.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
git diff --check
passed
```

The local tests exercise an actual sandbox transform against a private test
oracle commitment; default-deny, typed confirmation, EOF cancellation,
cross-run denial, revocation, append-only review history, and stale descriptor
version behavior. The all-tool registry and verifier bytecode remain unchanged
in the sandbox integration test.

## Acceptance limits

This demonstrates an explicit local operator approval path for one fixed
built-in capability, not arbitrary tool registration, autonomous research, or
human maintainer identity authentication. It does not satisfy Issue #7's P5
dependency; Issue #6 still lacks a repeated, diverse, pinned-model comparison
showing a gain. Keep Issue #7 open and PR #31 Draft.
