# Issue #7: seeded declarative workflow sandbox trial (2026-11-17)

## Scope

This increment is a bounded P6 vertical slice, not a claim that METIS can
autonomously research and publish general workflows. A deterministic seeded
fixture generator emits two simple encoding families and a JSON plan with one
or two transforms. Its oracle commitment remains in the controller process;
the seed and plaintext are not stored in run artifacts or this report.

`WorkflowCandidate` rejects extra fields and accepts only up to four steps from
the existing `base32_decode`, `base64_decode`, and `hex_decode` artifact-tool
registry. The fixed sandbox runner revalidates the closed schema, reads only the
declared target, applies bounded standard-library transforms, and returns a
length plus SHA-256 digest. Plans cannot carry executable code or change the
tool registry, policy, or verifier.

## Evidence

The local isolated-container integration exercised both generated encoding
families. Each two-step workflow produced a 29-byte result whose digest matched
the private controller-side oracle. The selected image was
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`
(`linux/arm64`); METIS reported network `none` and no host mounts. The oracle
value and output content were not printed or stored.

Reproduction in this environment:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra tests/test_ctf_workflow.py
6 passed in 0.35s
.venv/bin/ruff check src/metis/core/ctf_workflow.py tests/test_ctf_workflow.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
```

The pytest command runs the real sandbox integration test against a temporary
SQLite database and a freshly generated runtime seed, in addition to schema,
reproducibility, and tamper-rejection tests.

## Limits and next gate

The workflow choices are deterministic fixture templates, not model-proposed
research. The runner returns only a digest, so it demonstrates controlled
execution and independent verification rather than a model-consumable analysis
output. There is no held-out evaluation, reusable workflow registry, or
maintainer approval API for publishing new capabilities. Keep Issue #7 open.
