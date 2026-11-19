# Issue #9: staged release-bundle workflow gate

## Change

This branch depends on PR #111, which adds the bounded offline
`metis.release_artifacts --verify-checksums` verifier. The tag-triggered
`.github/workflows/release.yml` now invokes it on the exact `dist/` wheel,
sdist and `SHA256SUMS` after generation and before package attestation or
publication. A workflow regression requires checksum generation, the fresh
wheel install and smoke test, bundle verification, attestation, and publication
in that order. It also requires the expected staged directory, tag, project
name and version arguments, and checks the step has no `if:` or
`continue-on-error:` bypass. Existing synthetic
CLI coverage creates a valid bundle, accepts it, substitutes archive bytes,
and confirms verification rejects the tampered bundle without rewriting its
checksum manifest.

## Validation

Environment: Python 3.12 virtual environment; synthetic wheel/sdist bundles.
Commands and observed results:

```text
PYTHONPATH=src .venv/bin/python -m pytest -o addopts='' -q tests/test_validate_release_artifacts.py
42 passed
.venv/bin/ruff check src/metis/release_artifacts.py tests/test_validate_release_artifacts.py
All checks passed!
.venv/bin/mypy src/metis/release_artifacts.py
Success: no issues found in 1 source file
PYTHONPATH=src .venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
PYTHONPATH=src .venv/bin/python scripts/check_blue_knowledge.py
{"status": "passed", "findings": 0}
git diff --check
passed
```

The exact staged-bundle command also passed on an actual locally built wheel
and sdist after generating their checksum manifest:

```text
PYTHONPATH=src .venv/bin/python -m build --outdir "$BUNDLE_DIR"
Successfully built metis_ctf-0.5.0.tar.gz and metis_ctf-0.5.0-py3-none-any.whl
PYTHONPATH=src .venv/bin/python -m metis.release_artifacts --dist-dir "$BUNDLE_DIR" --tag v0.5.0 --project-name metis-ctf --project-version 0.5.0 --write-checksums
Validated release distributions:
metis_ctf-0.5.0-py3-none-any.whl
metis_ctf-0.5.0.tar.gz
PYTHONPATH=src .venv/bin/python -m metis.release_artifacts --dist-dir "$BUNDLE_DIR" --tag v0.5.0 --project-name metis-ctf --project-version 0.5.0 --verify-checksums
Validated release distributions:
metis_ctf-0.5.0-py3-none-any.whl
metis_ctf-0.5.0.tar.gz
```

`BUNDLE_DIR` was a temporary directory. No tag or release was created.

No tag, GitHub release, OIDC token, attestation or publication was requested
or performed. Exact-head GitHub CI will be reported separately if available.

## Limits

The offline gate checks bounded bundle consistency only. Replacing both
archives and `SHA256SUMS` can still pass; the check does not establish source
authenticity or recipient provenance, and it does not prove GitHub OIDC,
attestation verification or release publication. Signed installer evidence,
release-run evidence and the remaining Issue #9 gates stay open. Running the
release workflow requires a separately authorized tag/release action.
