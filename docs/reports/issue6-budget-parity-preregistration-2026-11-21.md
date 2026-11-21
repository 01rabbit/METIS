# Issue #6 budget-parity and finalisation-call preregistration (2026-11-21)

## Why a new study

The symmetric replication
([results](issue6-symmetric-replication-results-2026-11-18.md)) was strongly
negative: single 56/60 oracle-verified and workflow-complete, multi 11/60
verified-and-complete, multi workflow completion 16/60 (−75 pp). The
retrospective failure breakdown
([2026-11-21](issue6-failure-breakdown-2026-11-21.md)) could not attribute the
44 multi failures to a category, because the run predated the PR #135/#140
failure classification and did not retain per-job calls or stop reasons. Two
confounds remained untestable in that dataset and are fixed here before any new
model call:

1. **Budget split was assumed, not varied.** Every multi run reached the
   8-call total; the data cannot show which specialist exhausted its 4-call
   share. The single arm never finished within 4 calls (mean 6.73 of 8).
2. **No finalisation call was reserved.** In 33 of 44 failed multi trials the
   protected oracle still verified the composed candidate (12 with both jobs
   marked failed), suggesting the components were produced but the job ended
   budget-exhausted before it could report — a finishing problem, not a
   reasoning problem. This is an inference the retained stop reasons could not
   confirm.
3. **The single baseline was at a ceiling (93%),** leaving almost no headroom
   for a measurable multi gain in either direction.

This prospective study implements the five design changes recommended at the
end of the failure breakdown. Prior results are retained as historical
evidence and are not confirmatory for this question.

## Frozen design

- **Question:** When each specialist is given a budget sufficient to finish its
  own subproblem and a finalisation call is reserved outside the work budget,
  does two-specialist decomposition improve protected-oracle completion or
  end-to-end latency over one specialist on bounded synthetic encoding tasks,
  at a non-ceiling single baseline? This evaluates the Codex CLI runner and the
  METIS controller path only. It is not an AlpacaHack solve-rate or general
  CTF-performance benchmark.

- **Runtime:** Codex CLI `0.169.0`, model `gpt-6.1-sol`, reasoning effort
  `low`; METIS memory retrieval disabled. Abort rather than silently substitute
  a model or CLI version.

- **Difficulty calibration (addresses recommendation 4).** Before the main run,
  a pre-declared calibration pilot of 12 single-arm tasks selects a per-task
  difficulty whose single-arm oracle completion lands in **40–60%**. Difficulty
  is raised by nesting encodings per component (one, two, or three reversible
  layers) at a fixed layer count chosen by the calibration. The calibration
  task instances use seed `20261121c` and are **disjoint** from the main task
  set; the chosen layer count is recorded before the first main-run model call
  and is not changed afterward. If no layer count in {1, 2, 3} yields a single
  baseline inside 40–60%, the study aborts and the calibration result is
  reported instead of a gain test.

- **Tasks (addresses recommendation 5).** 30 seeded tasks across all 15
  unordered pairs of {Base64, Base32, hex, Base85, Base64URL, percent
  encoding}, two task instances per pair; two fresh repetitions per task
  (60 paired cases; arm-runs per the arm count below). Each task contains two
  **independently** encoded 12-byte printable components; the protected expected
  value is SHA-256(component 0 + NUL + component 1). The two components share no
  bytes, keys, or order dependence, so decomposition adds no information-transfer
  cost between specialists. Each component is encoded with the calibrated number
  of nested layers; the layer identities are declared with the artifact so that
  decoding is deterministic and requires no guessing of the scheme.

- **Arms (addresses recommendations 2 and 3).** Three arms per paired case:
  - **S — single.** One specialist receives both declared artifacts, decodes
    both components, and returns both as lowercase hex in one JSON object
    through the private candidate channel.
  - **M-fixed — multi, fixed total.** Two specialists; one artifact each. The
    aggregate work budget equals the single arm's work budget, split evenly
    (⌈W/2⌉ and ⌊W/2⌋ turns). Each returns its one component as lowercase hex.
  - **M-parity — multi, per-specialist parity.** Two specialists; one artifact
    each. **Each** specialist receives the full single-arm work budget W (so the
    aggregate work budget is about 2×S). This directly tests whether even-split
    starvation, not decomposition itself, caused the prior failures.

  In **all three arms** a dedicated finalisation/report turn is reserved for
  each job **outside** the work budget W: a job that spends its full work budget
  still has one reserved turn to emit its candidate. Daybreak parses the
  intermediates and computes the same SHA-256 and calls the same protected
  fixture oracle for every arm. No arm computes or receives the final digest.

- **Information boundary.** Single arm receives both declared artifacts; each
  multi specialist receives exactly one. No shell, code execution, live
  service, network, or external answer source is used.

- **Work budget W.** W is fixed from the calibration as the single arm's
  observed call need at the chosen difficulty, rounded up to the next even
  number and with one headroom call added (so S is not itself starved). Per run:
  2 concurrent slots and 600 seconds. Failed, incomplete, invalid, or timed-out
  trials score zero. No substantive retries; transient retries consume the same
  reserved work budget, never the reserved finalisation turn.

- **Randomization.** Seed `20261121`; a separate predeclared seed determines
  within-case arm order among {S, M-fixed, M-parity}. Generate all tasks and
  order before the first main-run model call. Record both in the retained
  answer-free dataset.

- **Measurements (addresses recommendation 1).** Protected-oracle completion,
  elapsed seconds, observed and reserved work calls, the finalisation turn
  used/unused flag, runner-reported input/cached/output/reasoning tokens,
  mediated actions, synthesis/job completion, and — newly retained for every
  arm-run — the PR #135/#140 `failure_category` and `specialist_outcomes`, the
  **per-job** calls used, per-job stop reason, report-rejection count, and
  timeout/host-error flags. CLI/model and cost availability are recorded; missing
  usage or cost is `unknown`.

- **Analysis.** Pair arms within each exact repetition. Primary comparisons:
  S vs M-fixed and S vs M-parity on protected-oracle completion and latency.
  Secondary: M-parity vs M-fixed, to isolate the budget-split effect. Estimate
  mean differences with a 10,000-sample paired bootstrap over the 30 task
  clusters, retaining both repetitions per sampled cluster. Report solve
  proportions, discordant pairs, failure-category distribution, per-job stop
  reasons, finalisation-turn usage, and budget use per arm. No broad CTF or
  AlpacaHack inference follows from a synthetic task set.

## Decision rule and limits

Issue #6 is accepted only if its repository acceptance criteria are met with
reproducible, retained evidence: a reliable paired gain for a multi arm over the
single arm under this matched design, at a non-ceiling baseline. A symmetric
synthetic result can support a narrow controller-path claim only; it does not
establish held-out CTF performance, AlpacaHack performance, production provider
cost, or native BridgeHost shared-budget enforcement. Interpretation of the
secondary comparison:

- If **M-parity** gains over S while **M-fixed** does not, the prior negative
  result is attributable to even-split starvation and a missing finalisation
  call, not to decomposition; record that and, if the aggregate call/token cost
  of parity is not justified by the gain, still keep single as the default.
- If **neither** multi arm gains over S at a 40–60% baseline, keep #6 open and
  report the uncertainty and the measured resource tradeoff; do not report any
  configuration difference as a gain.
- If the calibration cannot place the single baseline inside 40–60%, abort and
  report the calibration, not a gain test.

This study cannot establish P7 held-out CTF performance, generalization beyond
these encoding tasks, or native shared-budget enforcement.

## Privacy and integrity

Do not persist component plaintexts, final digests, candidate values, oracle
answers, or candidate file paths in run events or Git. Store the private oracle
with mode `0600` outside all run artifact roots; verify and purge each candidate
handoff immediately after scoring. Delete temporary run/artifact/oracle roots
after the study, including on interruption where possible. Retain only task IDs,
encoding-pair IDs, nesting-layer count, arm order, METIS run IDs, aggregate and
per-job counters, failure categories, stop reasons, completion state, and the
protected oracle boolean in the report and dataset.
