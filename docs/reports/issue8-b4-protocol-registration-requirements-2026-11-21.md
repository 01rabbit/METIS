# Issue #8 B4: pre-registration requirements for the held-out comparison protocol (2026-11-21)

## Purpose

Blocker B4 in the
[#8 blocker inventory](issue8-blocker-inventory-2026-11-21.md) is: *no
independent oracle or registered protocol exists for the next comparison, and a
new protocol must be registered before any comparison call.* This note fixes the
**pre-registration requirements** — the complete set of conditions and artifacts
that must be committed and externally fixed before the first model call of a
#8 end-to-end comparison. It is a requirements/acceptance spec, not itself a
protocol instance and not a gain claim. No model call or study run is involved.

## What the existing machinery already binds

`python -m metis.evaluation.heldout_protocol prepare PROTOCOL.json`
([protocol report](issue8-heldout-protocol-2026-11-19.md)) validates a
prospective comparison with no model or network call and prints its canonical
SHA-256 and deterministic task/repetition/arm schedule. The protocol fixes task
strata and exposure, distribution hashes, model and runtime pins, arm settings
and prompt hashes, equal budgets, repetitions, and the bootstrap seed. For a
real-model study the declared aggregate cap is at most 50 model calls and
7,200 seconds, the matrix is capped at 2,000 slots, and `finalize` rejects
observed aggregate use above those limits.

`finalize-acceptance`
([signed-control gate](issue8-signed-control-acceptance-gate-2026-11-20.md))
returns `null` for every control-dependent acceptance score unless a detached
control manifest, an Ed25519 signature, and the reviewer public key whose
SHA-256 fingerprint is pinned in the protocol are supplied and verified by
`heldout_control_attestation.py`. An unverified study is never presented as a
measured zero.

## What the machinery cannot self-prove (the two real B4 gaps)

Both are recorded as limits of the current tools and must be satisfied by
registration discipline, not by the finalizer:

- **G1 — external pre-call timestamp of the protocol hash.** The tool "cannot
  independently prove when that protocol was first committed"; `prepare` assigns
  run IDs afterward and is "not a proof that the study was registered before any
  model call."
- **G2 — independent oracle and reviewer source material.** The reviewer
  signature "does not independently validate the reviewer's source material,
  prove the tasks are solvable, prove exposure history, or authenticate trial
  verdicts." No production reviewer key or signed control package exists yet.

## Pre-registration requirements (all mandatory before the first model call)

### R1 — Frozen protocol artifact
A single `PROTOCOL.json` that `heldout_protocol prepare` accepts, declaring:
task strata and per-task exposure, distribution hashes, model and runtime pins,
each arm's settings and prompt hashes, equal per-arm budgets, repetitions, the
bootstrap seed, and the reviewer-key SHA-256 fingerprint. Its canonical SHA-256
(the "protocol hash") is the registration identity.

### R2 — External pre-call timestamp of the protocol hash (closes G1)
The protocol hash must be committed to the repository and carried by a PR whose
CI run timestamp precedes the first model call, and that commit/run must be
recorded in the study report. The first binding's run ID must be shown to be
created after that timestamp. No model call may be made before the protocol hash
is externally timestamped this way.

### R3 — Independent oracle (closes G2, part 1)
A solvability/verdict oracle **independent of the solving runner** gives the
authoritative correct/incorrect for every task:
- For CTF tasks, an official verifier; otherwise a reliable local oracle whose
  construction is declared in the protocol.
- The oracle store is mode `0600`, kept outside every run/artifact root, and is
  never read by any specialist or by memory retrieval.
- The model's self-report never counts as a verdict. Unknown, missing, invalid,
  timed-out, or unverifiable outcomes score zero (fail-closed).
- Each task must be shown solvable by the oracle before the comparison (a
  declared, reviewer-signed solvability assertion per R4), so a zero is a
  solver failure, not an unsolvable task.

### R4 — Independent reviewer and key provenance (closes G2, part 2)
A production Ed25519 reviewer key, held by a reviewer **independent of the
operator who runs the comparison**, signs the answer-free control manifest
(per-task `control` = verified/unverified and `exposure`). The protocol pins the
key's SHA-256 fingerprint (so the key cannot be swapped without changing the
protocol hash). Acceptance scores come only from `finalize-acceptance` with that
verified signature; `finalize` alone yields `control_attestation_status: absent`
and null acceptance scores.

### R5 — Exposure and leakage control
Every task is labelled `unseen`, `prior_solved`, `prior_answer`, or `unknown`;
only `unseen` tasks contribute to held-out acceptance. Memory retrieval is
disabled for the comparison; distribution hashes and the exposure manifest are
fixed in R1 and signed in R4. No answer, candidate, or oracle value may enter
run events, logs, Git, or reusable memory.

### R6 — Capability precondition (links B1/B2)
A real-model comparison may dispatch a specialist only through a runner that
declares `hard_token_budget_enforced` true; the held-out path otherwise fails
closed. Until B1 (runner cap) and, for the pinned-llama arm, B2 (proven
token-work bound) are satisfied, no real-model comparison call is authorized;
synthetic capability runners exercise the pipeline but are not benchmark
evidence. The declared aggregate cap must stay within 50 calls / 7,200 s /
2,000 slots, and finalization must reject any overage.

### R7 — Scoring and decision rule
Count oracle-verified solves only; record failures, elapsed time, and model
calls/tokens. State before any call which measured outcome supports which
settings choice, including that a negative or inconclusive result is valid and
keeps the simpler baseline. No broad or general-CTF claim follows.

### R8 — Retention and integrity
Retain only task IDs, strata/exposure labels, distribution hashes, arm settings,
protocol hash, reviewer-key fingerprint, run IDs, aggregate/per-job counters,
oracle booleans, and the manifest/signature digests. Never retain plaintext,
candidate values, final answers, oracle source material, or candidate file
paths. Purge each candidate handoff immediately after scoring and delete
temporary roots on completion or interruption.

## Registration checklist (order is the gate)

1. Author `PROTOCOL.json`; run `prepare`; record the protocol hash. *(R1)*
2. Build the independent oracle and the solvability assertions; store the oracle
   mode `0600` outside artifact roots. *(R3)*
3. Independent reviewer signs the answer-free control manifest with the pinned
   key. *(R4, R5)*
4. Commit the protocol hash and open a PR; let its CI timestamp stand as the
   external pre-call timestamp; record the commit/run. *(R2)*
5. Confirm R6: the authorized runner reports `hard_token_budget_enforced` true
   (B1, and B2 for the llama arm); otherwise stop — the comparison is not yet
   authorized.
6. Only then make comparison calls; `finalize-acceptance` with the signed
   manifest and reviewer key; report per R7/R8.

## Dependency and budget

B4 registration can be **authored and the oracle/reviewer prepared with zero
model budget**; steps 1–4 and 6's finalize are offline. The comparison calls in
step 6 are gated by R6 (B1/B2) and are the only part that spends model budget —
that is B5, not B4. This spec does not itself register a protocol, create a
reviewer key, build an oracle, or run a study; it fixes the requirements those
steps must meet.
