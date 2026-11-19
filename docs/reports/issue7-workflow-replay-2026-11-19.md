# Issue #7: bounded workflow replay

The new `metis workflow replay` command executes one registered declarative
workflow twice against the same run artifact in the existing isolated sandbox.
It compares the workflow digest, step count, output size and digest, and
sandbox engine/image/network/mount metadata. A controller-held SHA-256
commitment can be supplied through a private file; the command returns only
the reproducibility and oracle-match booleans. Output bytes, their digests,
the private commitment, and derived artifact paths are omitted from its JSON.

Both executions still register bounded untrusted derived artifacts under the
run. The fixed allowlist, capability review, no-network/no-host-mount sandbox
and existing verifier are unchanged. A mismatch or failed second execution
cannot be mistaken for a verified solve. The CLI suppresses private-file paths
in replay errors and does not initialize a database before reading an invalid
commitment file.

The synthetic regression suite passed with the pinned Linux ARM64 image:
`14 passed` in `tests/test_ctf_workflow.py`. It includes a real-container
replay, mismatch/failure cases, oracle comparison, and a private-path CLI
failure check. Ruff, mypy, `scripts/check_repo.py`, and `git diff --check`
passed locally. This is reproducibility evidence for the fixed workflow
contract, not model-generated research or P6 acceptance. Issue #7 remains open
while Issue #6's measured-gain dependency is unmet.
