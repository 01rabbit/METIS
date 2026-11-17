# Issue #6 real-model follow-up pilot results (2026-11-17)

## Outcome

The preregistered six-pair exploratory pilot completed on `gpt-6.1-sol`, Codex
CLI `0.169.0`, reasoning effort `low`, with the preregistered fixed seed and
randomized arm order. The tasks were synthetic local fixtures, not CTF
challenges. The protected oracle accepted the multi-specialist result in 6/6
pairs and the single-specialist result in 0/6 pairs. METIS report completion
alone did not imply a correct candidate: all six single-specialist jobs
completed their reports, but each candidate failed the oracle.

| Measure | Single specialist | Two specialists |
| --- | ---: | ---: |
| Oracle verified | 0/6 | 6/6 |
| Mean elapsed time | 53.79 s | 26.59 s |
| Median elapsed time | 52.10 s | 26.80 s |
| Model calls | 36 | 48 |
| Mediated actions | 24 | 24 |
| Mean input tokens | 63,374 | 82,433 |
| Mean output tokens | 888 | 721 |

Across all pairs, single-minus-multi elapsed time was 17.177–32.178 seconds
(mean 25.534 seconds). The two-specialist arm used two more reserved model
calls and more input tokens per pair, while parallel execution reduced wall
time in this narrow task family. Monetary cost was unavailable. The descriptive
sample is too small and narrow for a significance or generalization claim.

## Interpretation

This run supports continuing toward a properly powered benchmark: it shows a
large signal on tiny independent decoding tasks and demonstrates the real-model
measurement path with a protected oracle. It does not establish a general
specialist gain, CTF solve-rate improvement, or issue acceptance. Issue #6
remains open. The acceptance requirement remains a preregistered, diverse set of
at least 30 distinct tasks with two repetitions, paired uncertainty, and a
demonstrated gain. The upcoming benchmark should include harder and mixed
categories and account for correctness, elapsed time, calls, tokens, and cost.

## Measurement path correction

The first six-pair attempt did not reach a model response because Codex CLI
strict output schema rejected the nested optional proposal-options object. The
production schema now represents proposal options as JSON text, which the
controller parses back to an object and validates through the existing
scheduler contract. Regression tests cover strict object requirements,
valid normalization, and malformed/non-object JSON rejection. The successful
pilot above was run after this fix.

## Reproduction and privacy

The experiment used a temporary synthetic run root and a mode-0600 oracle file
outside each run's artifact root. Candidate values were verified locally and
purged from the run ledger after each check. Raw candidates and oracle contents
are intentionally excluded from this report. The exact preregistration is
`docs/reports/issue6-real-model-followup-preregistration-2026-11-17.md`; the
runner and seeded artifacts were temporary and are not committed. Calls,
tokens, elapsed time, correctness, and action counts are preserved in this
summary.
