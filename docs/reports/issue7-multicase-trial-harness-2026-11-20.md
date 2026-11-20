# Issue #7 bounded multi-case workflow trial harness

This change adds an answer-free batch interface for the existing local
declarative workflow trial. A private JSON manifest supplies 1–32 stable case
IDs and sibling fixture/oracle filenames. The complete manifest and every
bounded fixture and private SHA-256 commitment are snapshotted and validated
before the run workspace is created, the sandbox configuration is initialized,
or a proposer is called. Duplicate case IDs, input filenames, and fixture
contents are rejected. Cases run in sorted case-ID order.

Each case reuses the fixed schema and digest-only sandbox replay. The report
contains stable case IDs, selected registered steps, boolean replay outcomes,
safe failure codes, and an aggregate whose denominator includes every case.
It omits run IDs, file paths, fixture digests, oracle values, exception text,
and decoded output. The legacy generated two-family trial and the single
`--fixture`/`--oracle` invocation remain available. `--manifest` is mutually
exclusive with those legacy options.

Malformed workflow proposals and explicit replay/oracle mismatches count as
failed cases. Proposer process, sandbox configuration, run storage, and replay
exceptions abort the batch with a generic sanitized error instead of being
counted as model failures. The private manifest itself is checked for extended
ACL grants on macOS; each fixture is also checked against every case's oracle
commitment before a run starts.

Validation performed for this code change:

- On Python 3.13.14, `uv run --extra dev pytest
  tests/test_workflow_model_trial.py tests/test_ctf_workflow.py
  tests/test_cli.py -ra`: 84 passed, 4 skipped. The skips require the optional
  immutable sandbox image.
- `uv run --extra dev ruff check src tests scripts`, `uv run --extra dev mypy
  src/metis` (112 modules), `git diff --check`, and `uv run python
  scripts/check_repo.py` all passed.
- Tests use deterministic proposer and replay doubles for this new batch
  behavior; no live model, provider, CTF, credential, release, or publication
  action was performed.
- Adversarial checks cover malformed and oversized manifests, more than 32
  cases, duplicate IDs and paths, traversal paths, and no proposer/configure/
  run-workspace side effects on invalid intake; duplicate fixture bytes and
  cross-case oracle disclosure; strict replay booleans and infrastructure
  error separation.
- Privacy checks cover sorted stable IDs, result projection, and preservation
  of failed cases in the aggregate denominator.

This harness improves repeatable data collection over declared synthetic
encoding families. It does not itself create unseen families, measure a model,
establish held-out CTF performance, or satisfy the unmet Issue #6 P5 measured
gain dependency. Real model trials remain separately operator-authorized.
