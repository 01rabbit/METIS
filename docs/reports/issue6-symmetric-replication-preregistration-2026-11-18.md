# Issue #6 symmetric real-model replication preregistration (2026-11-18)

## Why a new study

The 2026-11-17 study protocol gave the single specialist responsibility for
computing the final digest, while Daybreak computed it in the multi-specialist
arm. That bundled answer composition with the decomposition treatment. The
prior results are retained as historical evidence but are not confirmatory for
this question. This prospective replication fixes the composition path before
any new model call.

## Frozen design

- **Question:** Under equal aggregate model-call, mediated-action, slot,
  wall-clock, model, and input-artifact budgets, does two-specialist task
  decomposition improve protected-oracle completion or end-to-end latency on
  bounded synthetic encoding tasks?
- **Runtime:** Codex CLI `0.169.0`, model `gpt-6.1-sol`, reasoning effort `low`;
  METIS memory retrieval disabled. Abort on version mismatch.
- **Tasks:** 30 seeded tasks across all 15 unordered pairs of Base64, Base32,
  hex, Base85, Base64URL, and percent encoding, two task instances per pair;
  two fresh repetitions per task (60 paired cases; 120 arm-runs). Each task
  contains two independently encoded 12-byte printable components. The
  protected expected value is SHA-256(component 0 + NUL + component 1).
- **Symmetric composition:** Both arms return only intermediate decoded
  components in the private candidate channel. The single specialist returns
  one JSON object with both components as lowercase hex; the two specialists
  each return one component as lowercase hex. The Daybreak controller parses
  the intermediates, computes the same SHA-256, and calls the same protected
  fixture oracle for both arms. No arm computes or receives the final digest.
- **Information boundary:** Single arm receives both declared artifacts. In
  the decomposed arm, each specialist receives exactly one artifact. No shell,
  code execution, live service, network answer source, or external answer
  source is used.
- **Budgets:** Per run, maximum 8 reserved model calls, 4 mediated artifact
  actions, 2 concurrent slots, and 600 seconds. Single assignment gets 8 turns;
  two specialists get 4 turns each. Failed, incomplete, invalid, or timed-out
  trials score zero. No substantive retries.
- **Randomization:** Seed `20261118`; separate predeclared seed determines
  within-pair arm order. Generate all tasks and order before the first model
  call. Record both in the retained answer-free dataset.
- **Measurements:** Protected-oracle completion, elapsed seconds, observed and
  reserved calls, runner-reported input/cached/output/reasoning tokens,
  mediated actions, synthesis/job completion, CLI/model, and cost availability.
  Missing usage or cost is `unknown`.
- **Analysis:** Pair arms within each exact repetition. Estimate mean latency
  and solve-rate differences with a 10,000-sample paired bootstrap over 30
  task clusters, retaining both repetitions per sampled cluster. Report
  failures, discordant outcomes, budget use, and interval. No broad CTF or
  AlpacaHack inference.
- **Retention:** Save only task IDs, encoding-pair IDs, arm order, METIS run IDs,
  aggregate counters, completion state, and the protected oracle boolean. Do not
  save component bytes, plaintext, final digests, candidate values, candidate
  file paths, or the oracle store. Delete temporary run/artifact/oracle roots
  after the study, including on interruption where possible.

## Decision rule and limits

Issue #6 is accepted only if its repository acceptance criteria are met with
reproducible, retained evidence. A symmetric synthetic result can support a
narrow controller-path claim; it does not establish held-out CTF performance,
AlpacaHack performance, production provider cost, or native BridgeHost shared
budget enforcement. If this study fails to show a reliable paired gain, keep
#6 open and report the uncertainty and measured resource tradeoff.
