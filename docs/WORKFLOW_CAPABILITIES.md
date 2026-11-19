# Workflow capability review gate

Declarative workflow candidates may use the three base transforms already
listed in `ARTIFACT_TOOLS`. A new workflow capability is denied by default.
The only review-gated capability currently implemented is the fixed built-in
`rot13_decode` transform.

## Operator flow

1. Inspect the run and proposed workflow before granting the capability.
2. Approve it for one run by running
   `metis workflow --database PATH approve RUN_ID rot13_decode` and typing the
   exact confirmation printed by the command. The command shows the descriptor
   ID, version, implementation hash, and bounds first; the confirmation phrase
   includes the version, descriptor hash, and run ID.
3. Check the active grant and append-only review history with
   `metis workflow --database PATH status RUN_ID`.
4. Revoke it for that run with
   `metis workflow --database PATH revoke RUN_ID rot13_decode`, again typing
   the exact confirmation.

To repeat a declared workflow in the isolated sandbox, use
`metis workflow --database PATH replay RUN_ID --target INPUT_ARTIFACT --workflow-artifact PLAN_ARTIFACT`.
The command runs the same plan twice against the original input and reports
only whether the bounded outputs and sandbox identity match. Optionally pass
`--oracle-sha256-file PRIVATE_FILE` to compare both outputs with a controller-
held commitment; neither the commitment nor output digests are printed.
Each replay consumes two bounded sandbox actions and registers two untrusted
derived artifacts. A failed or mismatched run does not certify a solve.

The CLI records the local OS username, timestamp, decision, fixed capability
version, and SHA-256 of its canonical descriptor. The descriptor digest binds
the approval to the implementation snippet and its fixed input/output limits.
An implementation/version change makes an older grant ineffective. Review
history has local SQLite update/delete guards; this is not tamper-proof against
someone who can replace or rewrite the database, and the OS username is not a
cryptographically authenticated reviewer identity.

Approval applies only to the named run. It does not come from workflow JSON,
agent intents, or another run. The controller checks the approval and passes a
restricted allowlist to the fixed sandbox runner, which checks the workflow
again. The output remains bounded and is stored as untrusted derived data. The
capability does not add to the global artifact tool registry or modify policy,
the verifier, network access, or deployment permissions. The runner accepts no
source code, shell commands, imports, paths, or endpoints from proposals.

Future capabilities require a reviewed METIS code change that adds one fixed
built-in implementation, a versioned descriptor, sandbox enforcement, and
tests before the capability can be exposed to the approval CLI. This gate is
for reviewed built-ins; it is not a plugin loader or self-extension mechanism.

## Evidence

The sandbox-backed test procedure and exact environment are in
[`issue7-capability-review-2026-11-17.md`](reports/issue7-capability-review-2026-11-17.md).
Issue #7 remains open while its P5 dependency and broader P6 evidence gates are
unmet.
