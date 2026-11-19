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
Before decoding, the sandbox checks the staged plan against the exact bytes
validated by the controller. The controller also checks the digest of the
input read by the sandbox against the declared artifact before registering
the output. Replay compares the input, plan and output digests along with the
sandbox identity and platform. Optionally pass
`--oracle-sha256-file PRIVATE_FILE` to compare both outputs with a controller-
held commitment. The command omits the commitment and all digests from its
result.
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

## Unseen local model pilot

`scripts/issue7_unseen_trial.py` draws one fresh random instance from each
known encoding family. A real Codex session sees only encoded input and a schema restricted
to the three base transforms. Its proposed JSON is validated before intake.
METIS replays the plan twice through the pinned, network-free sandbox in
digest-only mode and checks both results against a private in-memory SHA-256
commitment. No decoded answer artifact is registered. The trial
prints only step names, run IDs, reproducibility, and match booleans. A model
proposal cannot request a new tool, policy, verifier, executable, path, or
endpoint. This is a bounded local pilot, not general CTF evidence.

## Externally prepared benign encoding fixture

Supply `--fixture` and `--oracle` together to `scripts/issue7_unseen_trial.py` to
evaluate one operator-authorized offline encoding fixture. Use a single ASCII
encoding token of at most 65,536 bytes, with no trailing newline. A separate
reviewer should choose a fixture outside the seeded generator and compute the
SHA-256 of the exact expected decoded bytes before the trial, independently of
the proposer and METIS replay. Store the lowercase digest on its own line in
an owner-only regular file outside Git checkouts. Supply only file paths and
keep the run database and its artifacts in a private directory outside Git.

The intake snapshots both inputs in memory before calling the proposer. The
proposer receives only the encoded token. METIS reuses the pilot's three base
transforms and digest-only replay. The report adds the encoded fixture's
SHA-256 for identification. The expected digest and source paths stay out of
the report and run events. A missing or mismatched replay verdict fails the
trial. Independent preparation and whether the material is new to the model
depend on the reviewer; the intake checks file shape and bounds.

## Evidence

The sandbox-backed test procedure and exact environment are in
[`issue7-capability-review-2026-11-17.md`](reports/issue7-capability-review-2026-11-17.md).
Issue #7 remains open while its P5 dependency and broader P6 evidence gates are
unmet.
