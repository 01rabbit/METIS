# Issue #8 signed control acceptance gate (2026-11-20)

## Finding

The held-out protocol records task solvability and exposure fields as declarations.
`heldout_control_attestation.py` could verify a detached Ed25519 reviewer signature,
but neither the study finalizer nor the standalone analysis command required it.
Consequently, self-declared task controls could feed the `acceptance_eligible_*`
metrics without an authenticated independent review.

## Change

The generic `heldout_analysis.analyze()` and `heldout-protocol finalize` remain
available for historical and exploratory runs. They preserve diagnostic solve
counts but return `null` for all control-dependent acceptance scores and intervals,
so an unverified study is not presented as a measured zero. The protocol finalizer
sets `control_attestation_status` to `absent`.

The new `heldout-protocol finalize-acceptance` path requires a detached control
manifest, signature, and reviewer public key. The protocol now contains the
reviewer-key SHA-256 fingerprint, so it is included in the protocol digest and
run bindings. Finalization rejects a key that does not match this protocol pin,
then verifies the signature and task assertions before producing acceptance
analysis. The output records only the manifest and signature digests plus the
reviewer-key fingerprint, not the signature bytes or raw evidence. Existing
trial-verdict, resource, budget, and ledger checks still apply.

## Limits

The signature establishes that the holder of the pinned reviewer key signed the
control declarations for this protocol. It does not independently validate the
reviewer's source material, prove the tasks are solvable, prove exposure history,
authenticate trial verdicts, or prove that the protocol hash was externally
timestamped before dispatch. A protocol's key pin prevents swapping the key
without changing the protocol digest, but the tool cannot independently prove
when that protocol was first committed. No production reviewer key, signed
task-control package, model call, or held-out study was created for this
implementation. Issue #8 remains open.

## Validation

- `pytest tests/test_heldout_study_export.py tests/test_heldout_control_attestation.py`
- Ruff on `heldout_protocol.py` and `test_heldout_study_export.py`
- mypy on `heldout_protocol.py`
- `git diff --check`

The tests use synthetic protocols and a test-only Ed25519 key. They cover
unattested exploratory scoring, successful signature-bound acceptance controls,
missing signatures, wrong or unpinned keys, mismatched assertions, excluded
prior-exposed/unverified tasks, and the CLI path. The retained synthetic analysis
fixture was updated for null acceptance metrics when no reviewer key is verified.
