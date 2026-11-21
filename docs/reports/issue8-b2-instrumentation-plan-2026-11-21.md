# Issue #8 B2: token-work instrumentation plan pre-registration (2026-11-21)

## Purpose

Blocker B2 in the
[#8 blocker inventory](issue8-blocker-inventory-2026-11-21.md) is: *the pinned
llama-server has no proven upper bound on model-evaluated token work, because
failed decode and retry work is omitted from the reported usage, so
`hard_cap_capable` and `hard_token_budget_enforced` stay false.* The
[work-bound audit](../studies/issue8-llama-server-work-bound-audit.md) names the
next step — instrument every graph evaluation in the pinned binary and use the
trace to falsify a source-derived upper bound under adversarial conditions. This
note **pre-registers that instrumentation plan** before it is built or run: the
bound to be tested, what is measured, the adversarial matrix, and the pass/fail
rule. It is the acceptance-evidence source that the
[B1 runner contract](issue8-b1-runner-contract-2026-11-21.md) requires for the
pinned-llama Path A arm (its C1) and for the Path B per-call work bound. It is a
measurement plan, not a capability claim: no flag is flipped and no study is run
by this document, and nothing here authorizes a real-model held-out trial.

## What the audit already fixed (and why the reservation is not a bound)

The adapter starts one slot (`--parallel 1`), context 4096, no context shift,
no warmup, one `/completion` with `cache_prompt=false` and bounded `n_predict`,
and reserves `4096 + n_predict` after `/tokenize`
([audit](../studies/issue8-llama-server-work-bound-audit.md)). That reservation
is **not** a proven work cap, for three reasons recorded in the audit against
`ggml-org/llama.cpp` commit `b1b770d90`:

- A `decode()` failure makes `server-context.cpp:3649-3668` repeat the batch;
  `llama_process` (`:4717`) may halve its batch and retry (`:4763-4770`). The
  failed attempt's work is **absent** from `tokens_evaluated` / `tokens_predicted`
  (`server-task.cpp:340-341`). Reported usage therefore undercounts work.
- `llama-context.cpp:2140-2400` has its own memory-optimization retry and
  microbatch loop, and can dispatch to `encode` for a model without decoder
  memory (`:2143`). The full set of model-family/backend paths is not reduced to
  a verified accounting rule.
- A bound like `4096 * (n_predict + 1)` is *plausible but unproven*; it needs a
  formal bound on attempted batches, the work of each failed `llama_process`, and
  any re-evaluation across server transitions, plus a demonstration that model
  load/startup performs zero inference-token calls with `--no-warmup`.

## Measured quantity (M)

**M = the count of graph token positions submitted to model evaluation** for one
`/completion` request, aggregated over **every** attempt — successful and failed,
across batch-halving retries, memory-optimization retries, microbatch
iterations, and any `encode` dispatch — from request receipt to response or
termination. M is **not** provider billing tokens, **not** reported
`tokens_evaluated`/`tokens_predicted`, and **not** model-load or startup
allocation. It is the exact quantity the native work counter already claims to
meter for one consumed claim
([token-capability](../studies/issue8-token-capability.md)); this plan validates
that M is bounded, not merely reported.

### Instrumentation points (pinned patched binary only)
Instrument, in the pinned custom `llama-server` build, a monotonic counter
incremented at each graph evaluation entry with the batch's token count:

- every `llama_process` call (`server-context.cpp:4717`), including each
  post-halving retry (`:4763-4770`);
- the server-side batch repeat on `decode()` failure (`:3649-3668`);
- `llama_context::decode`/`encode` and the memory-optimization retry and
  microbatch loop (`llama-context.cpp:2140-2400`, dispatch at `:2143`);
- model load / startup, to show it contributes **zero** with `--no-warmup`.

The counter emits a terminal trace alongside the existing bounded native receipt;
it records only integer counts and the request nonce — no prompt text, no tokens,
no answer, no candidate — and shares the receipt's nonce/cap discipline so a
missing, malformed, duplicated, or mismatched trace fails the measurement run.

## The bound to falsify (B)

The source-derived upper bound **B = C · (n_predict + 1)**, where **C = 4096**
is the pinned context reservation and `n_predict` the dispatched output cap, as
conjectured in the audit. The plan derives, from the source, the maximum number
of attempted batches and the per-attempt token work, writes the resulting closed
form into the protocol, and then tries to **falsify** `M ≤ B` empirically. If the
source derivation yields a tighter or looser closed form than `C · (n_predict+1)`,
that derived form is registered as B before any trace is collected, with the line
and commit it is read from; B is fixed before measurement and not adjusted to fit
observed traces.

## Adversarial matrix (pre-declared, fixed before the first trace)

Each cell is run on the pinned binary with the pinned fixture; for each, record
M and compare to B. Cells are chosen to drive the retry and failure paths the
audit identified, not the happy path:

- **A1 Context-edge prompts** — tokenized length at `4096 − k` for
  `k ∈ {0, 1, 8}` and at the reservation boundary, with `n_predict` at its cap.
- **A2 Forced decode retry** — inputs/conditions that make `decode()` return
  false and trigger batch halving and the server-side repeat.
- **A3 Forced memory failure** — induce the memory-optimization retry / microbatch
  loop in `llama-context.cpp:2140-2400`.
- **A4 Encode dispatch** — a pinned model/condition that routes through `encode`
  (`:2143`), if within the pinned fixture; otherwise record as not-exercised and
  scope the bound to decoder models only.
- **A5 Timeout and cancellation** — terminate during health polling and
  mid-generation; confirm the trace still bounds the work performed before exit
  and that abandoned work is counted, not dropped.
- **A6 Concurrent callers** — two admitted requests contending (Path B admission
  must still serialize to one slot); confirm aggregate M across callers respects
  the atomic aggregate reservation (B1 C2).

Each cell runs a pre-declared fixed number of repetitions with a recorded seed;
all cells, inputs, and the binary SHA-256 are fixed before the first trace.

## Pass / fail rule (falsification, not self-declaration)

- **Falsified (flag stays false):** any single trace in any cell with `M > B`,
  or any run with a missing/malformed/mismatched trace, falsifies the bound. B2
  is not cleared; the counterexample cell and M are reported.
- **Provisionally bounded:** only if **no** trace across the entire pre-declared
  matrix exceeds B, and A1–A6 were actually exercised (or explicitly scoped out
  with reason), may B2 be reported as satisfied for the pinned build — and even
  then M is a model-evaluated-work bound for *this* patched llama.cpp build on
  *this* fixture, never a provider billing cap and never a qualification of
  another model or general held-out execution.
- The flag `hard_cap_capable` / `hard_token_budget_enforced` may be flipped true
  only with this retained, reproducible trace evidence; a declaration without it
  is a B1 contract violation, not a capability.

## Pins and environment

Pinned llama.cpp commit `b1b770d90`; pinned custom `llama-server` build with its
manifest-v2 identity (ELF dependency closure + `PT_INTERP`,
[token-capability](../studies/issue8-token-capability.md)); `--parallel 1`,
context 4096, `--no-warmup`, no context shift, `cache_prompt=false`, bounded
`n_predict`. Abort rather than substitute a commit, build, or runtime. Supported
hosts match the manifest: glibc Linux `aarch64`/`x86_64`; Darwin/musl native
launch stays refused. No model API credential is requested.

## Budget and scope

- **Budget:** zero provider/model budget and no held-out comparison call. This is
  local instrumentation of the patched binary against the public fixture, as in
  the existing native tests — which use a local fake server and never execute the
  patched binary or a model. Collecting the real traces runs the pinned binary
  locally, still with no provider call and no comparison study.
- **Not in scope:** this plan does not build the instrumentation patch, collect
  traces, flip any flag, register a comparison protocol, or run a study. It fixes
  the bound, the measured quantity, the matrix, and the decision rule those steps
  must meet.

## Privacy and integrity

The trace records only integer counts and the request nonce. Never persist prompt
text, tokens, candidate values, answers, oracle material, or candidate paths in
traces, run events, logs, or Git. Reuse the native receipt's nonce/cap
discipline; a missing, malformed, duplicated, oversized, or mismatched trace
fails the run. Delete temporary roots on completion or interruption.

## Relationship to other blockers

- B2 supplies the acceptance evidence for **B1** C1 (proven per-call work bound)
  on the pinned-llama Path A arm and for the Path B per-call work bound.
- A valid B2 result is a precondition of **B4** requirement R6 for any
  pinned-llama real-model comparison call; it does not by itself authorize B5.
- Concurrency cell A6 ties to **B1** C2 / **B3** (atomic aggregate reservation
  across parallel specialists).
