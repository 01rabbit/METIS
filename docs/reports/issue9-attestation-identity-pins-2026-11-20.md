# Issue #9 release attestation identity pins (2026-11-20)

Both the tag-triggered publishing workflow and the nonpublishing `main` drill
now ask GitHub CLI to verify more than the repository name. Each artifact's
certificate SAN must exactly match the expected workflow path and triggering
ref, its certificate issuer must be GitHub Actions OIDC, and the source ref and
commit must match the workflow run. Both verification commands reject
attestations made by self-hosted runners.

The tag workflow still checks that the tag points to a commit reachable from
`main` and that the tag matches the project version before it builds. It pins
the exact `release.yml` SAN at that tag and source commit before creating the
GitHub release. The manual drill pins its own workflow SAN on `main` and still
has no release-publication command.

Validation on macOS arm64, current worktree:

- `PYTHONPATH=src .venv/bin/pytest tests/test_validate_release_artifacts.py`:
  `44 passed in 0.38s`. Static tests check both workflows include repository,
  exact certificate identity, GitHub Actions OIDC issuer, source ref, source
  digest, and runner restrictions.
- `ruff check src tests scripts`: passed.
- `python scripts/check_repo.py`: passed with 0 findings.
- `git diff --check`: passed.
- No tag, release, signing workflow run, or external attestation was created
  for this change.

This changes workflow policy checks only. It does not re-run the existing main
attestation drill, publish a release, verify an installed package, or satisfy
Issue #9's P7 dependency and remaining operational gates.
