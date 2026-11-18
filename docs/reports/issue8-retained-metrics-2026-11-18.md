# Issue #8 retained benchmark metrics interface (2026-11-18)

## Result and boundary

P7 now has a typed, answer-free metrics schema and a reproducible analysis path
in `src/metis/evaluation/heldout_analysis.py`. This is an infrastructure advance,
not a new held-out experiment. No challenge page, distribution, answer,
authenticated service, or official submission was accessed for this change.
Issue #8 remains open.

The retained input and summary under `docs/reports/fixtures/` are explicitly
**invented analysis fixtures**: three task IDs, two repetitions and four arms
give 24 artificial rows. Their run identifiers, evidence sequence numbers,
oracle booleans, resources and outcomes are test data, not ledger evidence.
There was no solver, model, protected oracle, runtime or performance measurement.
The fixture's numerical solve differences must never be cited as measured gains.

## Interface and safeguards

The schema retains only fixed structured fields: task/category/difficulty,
split, exposure, solvability-control declaration, immutable model/runtime
identifiers supplied by the exporter, aggregate caps, run/event references,
verifier provenance and booleans, completion/failure class and resource metrics.
It rejects extra fields, unrestricted text, NaN/infinity, coercions, duplicate
task IDs or run IDs, incomplete/duplicate paired repetitions and unequal arm
budgets. The CLI reads at most 10 MB and prints a generic error on rejection;
Pydantic validation details could echo rejected private input and are suppressed.
This reduces accidental answer leakage; it cannot determine whether a permitted
identifier was deliberately populated with private data.

Each configured arm must have every selected task and repetition. Contaminated,
development and unknown-exposure rows stay in the original denominator and
score zero. Archive-local comparisons, missing verifiers, incomplete workflows,
declared failures, unresolved solvability controls and observed cap overruns cannot score.
Unresolved controls also have an explicit excluded-trial count. Only complete,
eligible, within-cap results declared verified by an official or protected
fixture oracle can score. These declarations do **not** authenticate evidence:
the controller exporter and reviewer must reconcile each run/event reference,
pre-existing protected oracle and scope against the original METIS ledger.
The analyzer never grants submission or solve-attestation authority.

The `scored_solves`/`solve_rate` fields are explicitly diagnostic correctness
metrics. P7 resource eligibility is reported separately as
`acceptance_eligible_solves` and `acceptance_eligible_solve_rate`, with separate
task-cluster intervals and paired contrasts. Those require observed actual
token and USD cost usage plus a declared USD cost cap, in addition to every
correctness/contamination/control/completion check. Unknown tokens, unknown
cost or an absent cost cap score zero for acceptance eligibility while staying
in its denominator; `acceptance_ineligible_resource_trials` counts these cases.
Thus the invented fixture's unknown USD costs yield zero acceptance-eligible
solves despite its positive diagnostic correctness counts. Even fully eligible
rows still require independent evidence review before acceptance.

The report generates deterministic 95% task-cluster bootstrap percentile
intervals for per-arm solve rates and paired differences, preserving all
repetitions in a task cluster. It reports task strata, contamination exclusions,
missing solvability controls, failures, untrusted verifiers, overruns, actual
calls/actions/time and unavailable tokens/cost as null with missing counts.
Equal declared caps are a validation rule; they do not prove equal actual
compute, prompt difficulty or controller assistance. Fixed model/runtime fields
are exporter declarations, not an environment attestation.

## Reproduction and validation

```sh
.venv/bin/python -m metis.evaluation.heldout_analysis \
  docs/reports/fixtures/issue8-analysis-synthetic-input.json
.venv/bin/python -m metis.evaluation.heldout_analysis METRICS.json \
  --database STATE.sqlite
.venv/bin/pytest -ra tests/test_heldout_analysis.py tests/test_issue6_benchmark_analysis.py
.venv/bin/ruff check src/metis/evaluation tests/test_heldout_analysis.py tests/test_issue6_benchmark_analysis.py
.venv/bin/mypy src/metis/evaluation/heldout_analysis.py src/metis/evaluation/issue6_diverse_analysis.py
```

The focused tests exercise retained-input/summary reproduction, matrix and
budget validation, contamination, local-oracle exclusion, incomplete workflows,
unknown resources, overruns, private-field rejection and sanitized CLI failure.
The accompanying Issue #6 regressions enforce exactly one/two completed jobs,
one record per case/arm and distinct repetition IDs. Ruff and mypy passed.
The focused suite passed 31 tests. All tests use trusted deterministic fixtures;
they do not exercise a challenge executable or external verification.

## Remaining experiment

Before any real model call, freeze a genuinely unseen task manifest and its
category/difficulty strata, independently protected oracle and solvability
controls, model/CLI/image pins, arm definitions and prompts, equal aggregate
caps, fresh-run repeated matrix and randomized arm order. Check selected task
IDs against prior runs/write-ups without revealing their answer content; exclude
known solved or answer-exposed tasks before freezing. A clean local declaration
cannot rule out unknown model-training contamination.

Export redacted per-trial metrics directly from controller evidence, retain
them for recomputation, and independently reconcile every scored verifier event.
Use equivalent final answer composition for all arms; the earlier Issue #6
comparison gave only multi an external controller-computed digest, so equal
caps there did not isolate specialist count. Record unknown usage/cost honestly,
analyze all preregistered failures, and avoid rerunning substantive failures.
The present interface still does not supply a full per-trial exporter,
randomized dispatcher, protected oracle generation, real repeated trials or
actual ablations. It does not demonstrate Issue #8's acceptance gate or broad
CTF performance.

## Ledger reference reconciliation follow-up (2026-11-18)

The analysis CLI accepts optional `--database STATE.sqlite`. In this mode it
opens the existing state database read-only and validates each referenced
run's complete event hash chain. Every `(run_id, evidence_sequence)` must name
an existing event. A trial declared verified by an official oracle must point
to a `SOLVED` event with one of the official API/form verifier tags
(`official_ctfd`, `official_rctf`, `official_ksnctf`, `official_html`). A
protected-fixture verdict must point to `SOLVED` with
`local_fixture_oracle`. Browser-only UI attestations and local SHA commitments
are deliberately not upgraded to these provenance classes. Output contains
only aggregate reconciliation counts, no run IDs, and no database writes.

The check validates references and provenance tags; it cannot authenticate an
external protected oracle, validate the truth of exposure or solvability
declarations, attest actual environment pins/cost, or prove workflow completion
from an arbitrary run event. The full exporter and independent evidence review
remain necessary. Focused tests use invented, hash-valid SQLite event chains.
The exact focused run passed 39 tests across `test_heldout_analysis.py` and
`test_issue6_benchmark_analysis.py`; Ruff and mypy passed for both analysis
modules. Exact-head CI for the preceding `eb36968` commit passed Python,
sandbox and linux-arm64-seccomp checks; the reconciliation change is newer and
requires its own exact-head CI result.

## Read-only run snapshot increment (post-merge)

`python -m metis.evaluation.heldout_export STATE.sqlite RUN_ID` emits a
fixed-field, answer-free snapshot from one validated event-chain transaction.
It derives terminal status, last evidence sequence, official or protected
fixture verification type, first-to-last event span, executing-event count,
and controller model-turn/action counts when those tables exist. Missing tables
and provider token/cost usage remain `null`; model rationales, tool output,
candidate values and raw event details are never exported. The snapshot does
not infer workflow completion, prior task exposure or solvability, so it is not
a complete `Trial` and cannot alone score the P7 acceptance gate. The event
span includes idle time and must not be used as a benchmark trial's active
runtime.

The local focused exporter and analyzer suite passed, including a
secret-bearing event detail, missing counters, unknown run, corrupted chain and
sanitized CLI error.
Ruff, mypy and `git diff --check` passed for the new module and test. The next
step is a trial-level exporter that joins independently reviewed task metadata,
job/synthesis completion and actual provider usage to these ledger facts, then
reconciles each trial before the repeated held-out study.

Independent read-only review found that the event-count cap was checked only
after chain materialization and that mixed aware/naive timestamps could yield
an unhandled error. The exporter now checks the count before reading the chain,
requires timezone-aware endpoints, and returns a generic CLI rejection for
malformed input. Focused regressions and Ruff/mypy passed. These protections do
not make the snapshot a complete trial exporter.

Review follow-up: `official_browser_observed` is exported as the separate
`browser_observed` provenance with `oracle_verified=false`. It is an observed
platform state, not an API verifier verdict eligible for the study's score.
The official-verifier labels are now shared with the analyzer. If first-to-last
event time exceeds 24 hours, only `event_span_seconds` becomes `null`; the
validated chain and remaining fields are retained.
