# Issue #9 signed release workflow (2026-11-18)

## Implemented

Added a tag-triggered release workflow that accepts only strict `vMAJOR.MINOR.PATCH` tags matching `pyproject.toml`, and only when the tagged commit is reachable from `main`. It builds the wheel and source archive from the locked environment, checks both embedded metadata records, generates SHA-256 sums, and installs the wheel into a fresh virtual environment using hash-locked runtime dependencies. The installed CLI must pass `metis --version` and `metis doctor` before proceeding.

The workflow pins each third-party action by full commit SHA and grants write/attestation/OIDC permissions only to the release job. It creates GitHub artifact attestations, verifies each attestation with the repository identity, and only then creates the GitHub Release. The workflow was not triggered; no tag, attestation, or release was created.

## Local evidence

- `uv build --clear --no-create-gitignore --out-dir /tmp/metis-release-dist` produced one wheel and one source archive.
- `scripts/validate_release_artifacts.py` accepted the matching `v0.5.0` artifacts and rejects malformed tags, mismatched versions, malformed/missing distribution metadata, and unexpected files.
- The release artifact validator tests passed (7 tests).
- A fresh Python 3.12 virtual environment installed the lockfile-exported runtime dependencies offline with hashes, then installed the built wheel; `metis --version` reported `METIS 0.5.0` and `metis doctor` reported ready with the configured sandbox.
- Workflow YAML and invariants (tag trigger, least-privilege job permissions, full-SHA action pins) parsed and passed local assertions.

## Acceptance still open

No GitHub tag run has demonstrated that Actions OIDC produces attestations, that `gh attestation verify` succeeds against artifacts from this repository, or that release publication works end to end. No signed VM installer was produced. Host-reboot recovery, artifact/credential retention and secure storage, provider-side token revocation, and the dependent P7 benchmark release gate remain outstanding. Issue #9 remains open; this local implementation is preparation evidence only.
