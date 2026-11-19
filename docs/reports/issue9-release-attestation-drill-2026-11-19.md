# Issue #9 release attestation drill preparation

The new manual GitHub Actions workflow builds the current `main` commit,
validates the wheel and source archive against the project version, installs
the wheel with hash-locked runtime dependencies in a fresh environment,
attests the archives and checksum file, and verifies each attestation against
the repository identity. It has read-only repository contents permission and
contains no release-publication command. The job runs only for `main`.

This gives the release owner a reversible OIDC and package-provenance drill
before creating a version tag or publishing a release. After the workflow is
merged, run it with `gh workflow run release-attestation-drill.yml --ref main`
and inspect the exact run's verification output. A successful dry run would
not prove that the tag-triggered publication path succeeds.

Local validation: nine release-artifact tests, Ruff, `check_repo.py`, and YAML
parsing passed. The workflow has not run on GitHub, no tag or release has been
created, and Issue #9 remains open for signed release publication, host reboot
recovery, secure credential lifecycle, and the Issue #8 dependency.
