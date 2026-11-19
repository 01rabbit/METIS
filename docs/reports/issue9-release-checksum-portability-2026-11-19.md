# Issue #9: portable release checksums

The release workflow now generates `SHA256SUMS` from validated archives using only their asset names. GitHub Release downloads put the wheel, sdist, and checksum file in one directory, so `sha256sum -c SHA256SUMS` can verify them there. The previous workflow wrote `dist/` prefixes, which required recipients to recreate that build directory.

The manifest remains an ordinary checksum file. Authenticity depends on the GitHub artifact attestations and their independent verification, not on SHA-256 alone. A signed release, published assets, and recipient-side attestation verification have not been observed. Issue #9's P7, host reboot, and other security gates remain open.

From this worktree, run the focused tests with `PYTHONPATH=src python -m pytest tests/test_validate_release_artifacts.py` and lint with `ruff check src/metis/release_artifacts.py tests/test_validate_release_artifacts.py`.

Local execution used the parent checkout's Python 3.12 virtual environment with this worktree's `src` on `PYTHONPATH`: 10 focused tests passed in 0.10 seconds. Ruff passed for the two changed Python files, and `git diff --check` found no whitespace errors. The fixtures are synthetic wheel and sdist archives; the test checks the manifest's exact SHA-256 digests and asset names, then exercises the CLI flag in a subprocess. No release workflow run or published assets were involved.
