# Issue #6 diverse real-model paired benchmark preregistration (2026-11-17)

## Question and scope

Under equal run-level model-call, mediated-action, slot, wall-clock, model, and
artifact budgets, does two-specialist decomposition improve oracle-verified
completion or latency over one specialist on bounded local analysis tasks?
This is an evaluation of the Codex CLI runner and METIS controller path. It is
not an AlpacaHack solve-rate or general CTF-performance benchmark.

## Frozen design

- **Model/runtime:** `gpt-6.1-sol`, Codex CLI `0.169.0`, reasoning effort
  `low`; METIS memory retrieval disabled. Abort rather than silently substitute
  a model or CLI version.
- **Task set:** 30 distinct seeded synthetic tasks, drawn from 15 pairs of
  common reversible text encodings, with two independently generated task
  instances per pair. Every exact task instance is repeated in a fresh run
  twice. Each task consists of two independent 12-character printable ASCII
  components; the correct answer is lowercase SHA-256 of component 0, a NUL
  byte, and component 1. Encoding types are drawn from Base64, Base32, hex,
  Base85, Base64URL, and percent encoding. The private oracle remains outside
  run artifact roots.
- **Arms:** single specialist receives both declared artifacts and must decode
  both and produce the final digest. Two-specialist arm assigns one artifact
  to each specialist; each returns its decoded bytes only through the private
  candidate channel and Daybreak forms the same final digest. Neither arm can
  access the other's artifact. No code execution, live service, or external
  answer source is involved.
- **Per-run limits:** eight reserved model calls, four mediated artifact
  actions, two concurrent slots, 600 seconds. Single arm has one assignment
  capped at eight turns; the two-specialist arm has two assignments capped at
  four turns each. These are equal aggregate maxima. Transient retries consume
  the same reserved call budget.
- **Order:** generate all task instances and arm order before any model call.
  A fixed seed determines the task set and a separate fixed seed randomizes
  single/multi order independently for each task repetition. Never rerun a
  substantive model failure.
- **Scoring:** only the private fixture oracle counts as correct. Incomplete,
  invalid, failed, or timed-out outputs score zero. Scheduler report completion
  is recorded separately from oracle correctness.
- **Metrics:** correctness, elapsed seconds, observed and reserved model calls,
  input/cached/output/reasoning tokens, mediated actions, synthesis completion,
  and monetary cost. Record unavailable provider cost or usage as `unknown`.
- **Analysis:** compare arms within each exact task repetition. Report paired
  differences and a 95% paired bootstrap interval, resampling the 30 distinct
  task IDs as clusters and retaining both repetitions for each sampled task.
  Also report solve proportions, discordant pairs, failures, and budget use.
  No broad performance claim follows from a synthetic task set.

## Decision rule

The earlier six-pair pilot showed a latency signal but also higher calls and
input tokens for the multi-specialist arm. This larger run is justified as a
measurement-path follow-up, not as confirmation of a gain. Issue #6 acceptance
requires a demonstrated paired gain under this matched design; otherwise keep
the issue open and report the uncertainty and resource tradeoff. This study
cannot establish P7 held-out CTF performance, generalization beyond these
encoding tasks, or BridgeHost-native shared-budget enforcement.

## Privacy and integrity

Do not persist component plaintexts, final digests, candidate values, oracle
answers, or candidate file paths in run events or Git. Store the private oracle
with mode `0600` outside all run artifact roots; verify and purge each
candidate handoff immediately after scoring. Record only task IDs, transform
family IDs, arm order, aggregate metrics, and oracle booleans in the report.
