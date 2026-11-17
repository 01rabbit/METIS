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
.venv/bin/pytest -ra tests/test_heldout_analysis.py tests/test_issue6_benchmark_analysis.py
.venv/bin/ruff check src/metis/evaluation tests/test_heldout_analysis.py tests/test_issue6_benchmark_analysis.py
.venv/bin/mypy src/metis/evaluation/heldout_analysis.py src/metis/evaluation/issue6_diverse_analysis.py
```

The focused tests exercise retained-input/summary reproduction, matrix and
budget validation, contamination, local-oracle exclusion, incomplete workflows,
unknown resources, overruns, private-field rejection and sanitized CLI failure.
The accompanying Issue #6 regressions enforce exactly one/two completed jobs,
one record per case/arm and distinct repetition IDs. Ruff and mypy passed.
The focused suite passed 27 tests. All tests use trusted deterministic fixtures;
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
The present interface does not supply that exporter, randomized dispatcher,
protected oracle generation, real repeated trials or actual ablations. It does
not demonstrate Issue #8's acceptance gate or broad CTF performance.
