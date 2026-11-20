# Offline held-out control attestation

The verifier checks that an independently trusted reviewer signed the exact
held-out protocol's control and exposure assertions. It does not change
protocol finalization or grant access to any runtime or oracle.

```sh
python -m metis.evaluation.heldout_control_attestation \
    PROTOCOL.json CONTROL-ATTESTATION.json CONTROL-ATTESTATION.sig \
    --reviewer-key TRUSTED-REVIEWER.pub
```

The operator supplies a raw 32-byte Ed25519 public key from the independent
control reviewer over a trusted channel. The signature file contains the
detached 64-byte signature. The CLI emits only the protocol digest and row
count on success, or a generic rejection. Keep it offline.

The version-1 manifest has exactly four top-level fields. Use
`schema_version: 1`, `role: independent_control_reviewer`,
`protocol_sha256` from `heldout_protocol.digest()`, and `tasks`.
Include exactly one row per task. Each row contains
`task_id_sha256` and `source_id_sha256` (hashes of the respective ASCII
identifiers, with no newline), `distribution_sha256`, `evidence_sha256`
(a digest of a separately retained reviewer record), `control`
(`verified` or `unverified`), and the protocol's `exposure` classification.
Duplicate task identities and duplicate source/distribution pairs are rejected.
Use `signing_bytes(ControlAttestation.model_validate(...))` to prepare the
versioned, domain-separated canonical payload for an external signer.
Task order and JSON formatting do not affect the signature.

A successful check authenticates the reviewer's claims, including claims of
unknown exposure or an unverified control. It does not check the underlying
evidence, establish actual solvability or model-training exposure, require
review to precede study execution, verify trial outcomes, or authorize scoring.
The reviewer key and protection of independent evidence remain operator
responsibilities. Compute `evidence_sha256` over an answer-free reviewer
record. Keep any answer-bearing materials separately protected. A digest of
a predictable record containing a hidden answer can let readers test answer
guesses offline. The verifier cannot tell how a digest was constructed.
The sidecar has no expiry or revocation check.
