# Issue #7 multi-case real-sandbox replay (2026-11-20)

## Observed run

The harness implementation under test was from main commit
`353aac716cfb16b0908524b8fa80491807e01644`. The new optional integration test
`test_multi_case_manifest_replays_in_real_sandbox_without_leaking_oracle`
ran a reversed two-case private manifest through the real METIS workflow runner
and local Docker sandbox. The proposer was a deterministic in-process callback;
no model, provider, CTF service, credential, or submission was used.

The sandbox used the pre-existing immutable `linux/arm64` image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`.
Both cases were returned in sorted case-ID order and each ran twice for the
reproducibility check:

| Case | Fixture SHA-256 | Registered steps | Result |
| --- | --- | --- | --- |
| `alpha` | `1564c6622ba44e09df0179d270bbbcb0b4f4bc62b57427e785c5bb2daaee6e30` | `base32_decode`, `base64_decode` | `ok`, reproducible, oracle matched |
| `beta` | `41205c811398738a5670fbeb9f94133c67da09c876222a7951d77fcb94f25164` | `base64_decode`, `hex_decode` | `ok`, reproducible, oracle matched |

The returned batch summary was 2 total, 2 passed, 0 failed. All four sandbox
executions returned metadata containing `network=none`, `host_mounts=false`,
the configured image digest, and `linux/arm64`. Those fields are emitted by
METIS and are not an independent Docker-daemon inspection. During the test, a
spy captured the actual argument vectors passed to all four `docker create`
invocations. Each used the pinned image and explicit `linux/arm64` platform,
`--network=none`, `--read-only`, `--cap-drop=ALL`,
`--security-opt=no-new-privileges`, and `--pull=never`; none contained bind-mount
arguments. This verifies the command arguments sent by METIS, not the daemon's
independent interpretation of them. The runtime implementation streams inputs
over stdin rather than using host mounts. The test confirms that oracle
commitments, the answer, alpha's base64 intermediate, beta's hex intermediate,
the unwrapped candidate material, and temporary paths are absent from the
returned report, run events, SQLite/WAL files, and registered artifacts; only
the declared challenge and workflow artifacts remain in each run. The pytest
temporary directories were explicitly removed from the developer host
after validation. Run IDs and oracle commitment values are intentionally not
reported.

## Validation

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b \
METIS_TEST_SANDBOX_PLATFORM=linux/arm64 \
DOCKER_CONTEXT=colima-rosetta \
UV_PROJECT_ENVIRONMENT=/tmp/metis-issue7-uv-env \
uv run --offline --extra dev --python 3.13 pytest -ra \
  tests/test_workflow_model_trial.py tests/test_ctf_workflow.py \
  --basetemp=/tmp/metis-issue7-pytest-temp
77 passed in 3.37s

uv run --offline --extra dev --python 3.13 ruff check tests/test_workflow_model_trial.py
All checks passed!

python scripts/check_repo.py
{"status": "passed", "findings": 0}

git diff --check
passed
```

The test strengthens the real-sandbox evidence for deterministic multi-case
replay and output privacy. It does not evaluate model proposals, unseen-family
performance, held-out CTF success, or the unmet Issue #6/P5 measured-gain gate.
Issue #7 remains open.
