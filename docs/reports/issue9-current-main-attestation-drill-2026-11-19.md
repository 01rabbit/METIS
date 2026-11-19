# Issue #9: current-main release attestation drill (2026-11-19)

The manually dispatched [release attestation drill](https://github.com/01rabbit/METIS/actions/runs/44522221519) completed successfully on `main` commit `13619216e003597f159675583481054a9c84ddbe`. This is an unsigned release *candidate* build and provenance drill, not a published release.

The workflow built the wheel, source archive, and portable `SHA256SUMS` from the locked environment. It installed the wheel with hash-checked locked dependencies in a fresh environment, ran `metis --version` and `metis doctor`, created a GitHub artifact attestation for the candidate files, and successfully ran `gh attestation verify` against the wheel, source archive, and checksums. The [repository attestation](https://github.com/01rabbit/METIS/attestations/69636718) was uploaded to Rekor at log index `3996166211`. These claims are limited to the completed workflow steps and its source commit.

No tag, GitHub release, or installer was published by this workflow. It does not test installation on a clean macOS host, provider-side credential revocation, or the Issue #8 benchmark dependency. Issue #9 remains open.
