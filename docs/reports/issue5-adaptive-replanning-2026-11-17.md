# Issue #5 adaptive replanning evaluation (2026-11-17)

## Scope

`FixtureProvider` now accepts bounded, declarative fallback routes in the local
fixture plan. A route identifies the failed attempt, the only permitted evidence
(`invalid_input`), the untried alternate, and a rationale. The provider selects
that alternate only after the specified parser rejection. `invalid_text`,
execution errors, timeouts, policy failures, unclassified failures, malformed
plans, and already-tried alternates halt. Routes cannot add tools: each action
must be a distinct `ToolRequest` already present in the plan. A parser-rejection
route must preserve the exact input so that the failure is evidence about the
challenge payload rather than a separate probe. The benchmark below exercises
two different decoders. The fixture runtime's static allowlist remains
authoritative. The runner tracks attempted requests, enforces its existing
action/model/time budgets, rejects duplicate actions, and records the rationale
before execution.

Generated Crypto and Misc fixtures now also declare the exact parse failure
that justifies their alternate decoder. The paired evaluation's lightweight
runtime now matches the production worker's distinction between parser
rejection (`invalid_input`) and decoded non-text (`invalid_text`); Unicode
decoding errors are no longer counted as parser rejection.

## Paired comparison

The test uses 30 seeded private-oracle fixtures (15 Base64, 15 hex), with
distinct tool orders shuffled using a separate seed `20261120`. The assigned
first tool is the same for both arms on each fixture and its balanced order is
generated independently of the encoding fixture seed. Both tools receive the
same encoded challenge input; the alternate plan entry does not contain a
pre-decoded answer. Both arms use the same local transform runtime,
three-decision cap, 10-second wall-clock limit,
2-second per-tool timeout, and private oracle. The baseline tries its assigned
first action once and halts after a failed observation; it does not rely on the
runner's duplicate-action guard to enforce one-shot behavior. The adaptive arm
takes the declared alternate only after `invalid_input`.

| Policy | Verified solves | Mean tool actions |
| --- | ---: | ---: |
| Evidence-conditioned fallback | 30/30 | 1.467 |
| Fixed first-action baseline | 16/30 | 1.0 |

The paired solve-rate difference is 0.467, with a 95% paired bootstrap interval
of [0.300, 0.633] (seed `20261118`, 10,000 resamples, percentile bounds). The
result demonstrates the declared alternative route in both tool orders on
synthetic strings. It does not estimate real-model performance, held-out CTF
performance, or a general solve rate.

## Reproduction and limits

```text
.venv/bin/pytest -ra tests/test_runner.py
26 passed, 2 skipped in 0.88s
.venv/bin/ruff check src/metis/core/models.py src/metis/core/runner.py src/metis/core/fixtures.py tests/test_runner.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 51 source files
.venv/bin/pytest -ra -q
exit 0; optional Docker, platform-specific, and KSNCTF integration cases skipped
```

The two skips require the optional Docker image. The measured pair used a
lightweight local transform runtime, not the isolated container worker. The
test therefore validates the decision transition and oracle accounting, but
does not measure model usage/cost or prove Docker behavior. Broader P4 gates
remain open: generalized hypothesis evidence scores, contradiction and
stuckness tracking, semantic-equivalence repeat detection, diverse held-out
problems, and controlled real-model comparisons.
