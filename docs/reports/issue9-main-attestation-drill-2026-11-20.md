# Issue #9 main-branch attestation drill (2026-11-20)

## Observed run

The `release attestation drill` workflow completed successfully on GitHub
Actions run [44685127951](https://github.com/01rabbit/METIS/actions/runs/44685127951)
at 2026-11-20 06:08:18 UTC. It ran from `refs/heads/main` at commit
`353aac716cfb16b0908524b8fa80491807e01644`, the then-current main commit after
PR #127. The job used the GitHub-hosted `ubuntu-24.04` runner and Python 3.12.

All workflow steps succeeded:

1. Built an unsigned `metis-ctf` 0.5.0 wheel and source archive with pinned
   uv 0.13.5. The isolated build backend is declared as `hatchling>=1.25` and
   is not pinned by the project lockfile. The workflow validated release
   metadata and generated `SHA256SUMS`.
2. Installed the wheel into a fresh virtual environment using the locked
   runtime wheelhouse. `metis --version` and `metis doctor` passed; doctor
   reported `ready: true` and `mode: codex-native`. The sandbox was not
   configured, so this smoke test did not exercise sandbox execution.
3. Recomputed the wheel and source archive digests, confirmed `SHA256SUMS`
   matched them exactly, and revalidated release metadata and bundle contents.
4. Created one GitHub Build Provenance attestation containing all three
   subjects. The
   run log confirms the signatures were uploaded to the repository and the
   Rekor transparency log. The attestation bundle is visible at
   [attestation 70008857](https://github.com/01rabbit/METIS/attestations/70008857).
5. The workflow's verification step succeeded for each subject while checking
   the exact repository, drill workflow certificate identity, GitHub Actions
   OIDC issuer, `refs/heads/main`, source commit above, and rejecting
   self-hosted runners.

## Scope and limits

This is current-main evidence that the non-release workflow can build, install,
smoke-test, attest, and verify an exact candidate bundle. It produces
attestations, but it did not create a tag, GitHub Release, or publish package
assets. The ephemeral distribution files were not attached to a release.

The run does not establish the Apple Silicon controller plus isolated Linux VM
deployment, a host-reboot recovery, physical erasure or backup retention,
provider credential revocation, P8 acceptance, or the unmet Issue #8/P7
benchmark dependency. It is one successful release-provenance
drill and does not complete Issue #9. No completion checkbox or Issue state was
changed.
