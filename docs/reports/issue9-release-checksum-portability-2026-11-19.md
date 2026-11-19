# Issue #9: portable release checksums

The release workflow now generates `SHA256SUMS` from validated archives using only their asset names. GitHub Release downloads put the wheel, sdist, and checksum file in one directory, so `sha256sum -c SHA256SUMS` can verify them there. The previous workflow wrote `dist/` prefixes, which required recipients to recreate that build directory.

The main-branch attestation drill uses the same validator option and manifest format. This keeps its candidate artifact and checksum verification aligned with the tag-triggered release workflow; the drill still cannot publish a release.

The manifest remains an ordinary checksum file. Authenticity depends on the GitHub artifact attestations and their independent verification, not on SHA-256 alone. A signed release, published assets, and recipient-side attestation verification have not been observed. Issue #9's P7, host reboot, and other security gates remain open.

From this worktree, run the focused tests with `PYTHONPATH=src python -m pytest tests/test_validate_release_artifacts.py` and lint with `ruff check src/metis/release_artifacts.py tests/test_validate_release_artifacts.py`.

Local execution used the parent checkout's Python 3.12 virtual environment with this worktree's `src` on `PYTHONPATH`: 10 focused tests passed in 0.10 seconds. Ruff passed for the two changed Python files, and `git diff --check` found no whitespace errors. The fixtures are synthetic wheel and sdist archives; the test checks the manifest's exact SHA-256 digests and asset names, then exercises the CLI flag in a subprocess. No release workflow run or published assets were involved.

## Offline bundle verification

Copy the wheel, sdist, and checksum file to a stable local staging directory.
Supply the expected project and version from a trusted source.

```sh
python -m metis.release_artifacts --dist-dir /path/to/staged-bundle \
    --tag v0.5.0 --project-name metis-ctf --project-version 0.5.0 \
    --verify-checksums
```

This mode validates the package metadata and checks that the manifest matches
the exact two archives. It expects the canonical generator's wheel-first,
sdist-second order, release basenames, and LF line endings. It streams the
archive digests and reads at most one byte beyond the expected manifest size.
The staged bundle is read-only for this check. Successful verification shows
bundle consistency. Replacing both an archive and its manifest can still pass.
Verify artifact attestations through a separate trusted provenance check.
Keep staging paths stable during validation.

Twenty focused tests passed using synthetic archives. Cases include a
substituted wheel with unchanged package metadata, a missing manifest,
symlink, missing or duplicate lines, extra entries, traversal text, changed
digests, trailing content, and reorder. Ruff, mypy, the repository scanner
and diff check passed. No release was tagged, published, or downloaded.
