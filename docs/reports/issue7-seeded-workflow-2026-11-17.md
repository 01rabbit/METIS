# Issue #7: seeded declarative workflow sandbox trial (2026-11-17)

## Scope

This increment is a bounded P6 vertical slice, not a claim that METIS can
autonomously research and publish general workflows. A deterministic seeded
fixture generator emits two simple encoding families and a JSON plan with one
or two transforms. Its oracle commitment remains in the controller process;
the seed and oracle commitment are not stored in run artifacts or this report.

`WorkflowCandidate` rejects extra fields and accepts only up to four steps from
the existing `base32_decode`, `base64_decode`, and `hex_decode` artifact-tool
registry. The fixed sandbox runner revalidates the closed schema, reads only the
declared target, applies bounded standard-library transforms, and returns a
maximum 16 KiB output as Base64 plus a length and SHA-256 digest. The controller
revalidates encoding, byte count, and digest, then registers the bytes as a
run-scoped `.metis-derived/*.bin` artifact marked untrusted for later analysis.
Plans cannot carry executable code or change the tool registry, policy, or
verifier.

## Evidence

The local isolated-container integration exercised both generated encoding
families. Each two-step workflow produced a 29-byte result whose digest matched
the private controller-side oracle, and the output was read back from the
registered derived artifact. The artifact is marked untrusted and appears in
the run's declared artifact list; its bytes are not copied into the event
ledger. The oracle commitment is not present in the event JSONL. The selected image was
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`
(`linux/arm64`); METIS reported network `none` and no host mounts. The oracle
commitment is not stored in events or artifacts; the decoded output is stored
only in the scoped derived artifact.

Reproduction in this environment:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra tests/test_ctf_workflow.py
8 passed in 0.70s
.venv/bin/ruff check src/metis/core/ctf_workflow.py tests/test_ctf_workflow.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
```

The pytest command runs the real sandbox integration test against a temporary
SQLite database and a freshly generated runtime seed, in addition to schema,
reproducibility, and tamper-rejection tests.

Full-suite validation after this change used the same pinned sandbox image:
`467 passed, 18 skipped in 72.04s`. Ruff and mypy passed on the working tree.

## Limits and next gate

The workflow choices are deterministic fixture templates, not model-proposed
research. Only their bounded transformed output is reusable; the runner does
not create general analysis workflows. There is no held-out evaluation,
reusable workflow registry, or maintainer approval API for publishing new
capabilities. Keep Issue #7 open.
