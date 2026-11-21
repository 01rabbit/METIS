# Issue #6 symmetric replication: retrospective failure breakdown (2026-11-21)

## Purpose

The preregistered symmetric replication
([results](issue6-symmetric-replication-results-2026-11-18.md)) was strongly
negative: single 56/60 oracle-verified and workflow-complete, multi 11/60
verified-and-complete, multi workflow completion 16/60 (-75 pp). An external
review hypothesised that the cause is design rather than reasoning: the single
arm used about 6.7 of 8 calls, so a 4/4 split leaves each specialist unable to
finish. This note checks that hypothesis against the retained data only. No
model call or network access was used.

## Data

`docs/reports/data/issue6-symmetric-replication-2026-11-18.json` (120 answer-free
records). Retained per arm-run: `calls_observed`, `calls_reserved`, `actions`,
`job_states`, `oracle_verified`, `synthesis_complete`, `elapsed_seconds`, usage.

Not retained (the run predates the failure classification of PRs #135/#140):
`failure_category` / `specialist_outcomes`, per-job calls used, report-rejection
counts, timeout and host-error flags, per-job stop reason. No terminal-outcome
category distribution (call ceiling vs report rejection vs timeout vs host
error) can therefore be computed. Everything below that speaks to cause is a
labelled proxy.

## Method

`scripts/analyze_issue6_failure_breakdown.py` reads only the retained JSON and
prints deterministic JSON. Counts are tabulated per arm and per multi trial.
Proxies: "at total call cap" means `calls_observed >= 8`;
"verified despite failed job" means `oracle_verified` while at least one job
state is `failed`.

## Results

| Measure | Single (n=60) | Multi (n=60) |
|---|---|---|
| Workflow complete | 60 | 16 |
| Oracle-verified (any) | 56 | 44 |
| Verified and complete | 56 | 11 |
| Job states | 60 completed | 16 both done, 24 one failed, 20 both failed (64/120 jobs failed) |
| Calls observed | 6 x16, 7 x44 (mean 6.73) | 8 x60 |
| Actions used | 4 x60 | 4 x60 |
| Mean elapsed (s) | 43.3 | 26.2 |

Multi failed trials (44):

| Proxy | Count |
|---|---|
| At total call cap (8/8) | 44 of 44 (also 16 of 16 of the complete trials) |
| Oracle-verified despite a failed job | 33 (of which 12 had both jobs failed) |
| Not oracle-verified | 11 |
| All 4 actions used | 44 |

Budget-split proxies: 60/60 single runs used more than 4 calls (56 of the
verified ones). 60/60 multi runs reached the 8-call total, including every
trial that completed.

## Reading of the budget-split hypothesis

Undeterminable from this dataset, with mixed indirect evidence.

- Consistent: single never finished within 4 calls, and every multi trial,
  failed or not, consumed the full budget.
- Not discriminating: the total is always 8 in multi, so it cannot show which
  specialist hit its 4-call share. Calls at the cap are the norm for
  successes too (16/16), so the cap alone does not separate failure from
  success.
- Arithmetic against a pure "4 is too few for reasoning": a single run solves
  two artifacts in about 6.7 calls, roughly 3.4 per artifact, which fits in 4
  if per-artifact cost carries over. The data cannot confirm that it does.
- Suggestive of a finishing problem rather than a reasoning problem: in 33 of
  44 failed multi trials the protected oracle still verified the composed
  candidate, and in 12 both jobs were marked failed. The components appear to
  have been produced, but the job did not terminate as completed. A plausible
  mechanism is that the final report call was not reserved, so a job that used
  its share on work ended as budget-exhausted. This is an inference; the
  stop reasons needed to test it were not retained.

## What this does and does not establish

This is a retrospective exploratory analysis of an already completed study. It
is not a preregistered gain test and makes no claim about multi-specialist
gain. It does not establish the cause of the 44 failures, and it cannot
attribute any failure to a category (ceiling, rejection, timeout, host). The
verified-despite-failed count is a descriptive observation about job state
versus the oracle, not evidence of what the job did. The synthetic
short-text encoding task limits generalisation as stated in the original
results.

## Recommended design changes for the next preregistration

1. Record the failure classification (`failure_category`,
   `specialist_outcomes`) and per-job calls used in the retained dataset.
2. Compare a per-specialist budget parity arm (each specialist gets the
   single arm's observed need) against a fixed-total arm, so budget split is
   varied directly rather than assumed.
3. Reserve a dedicated report/finalisation call outside the work budget, in
   both arms.
4. Choose tasks with a non-ceiling single baseline (about 40-60%) so a gain
   can be measured; 93% leaves little headroom and a ceiling in the other
   direction hides it.
5. Use genuinely independent subproblems so that decomposition adds no
   dependency or information-transfer cost.
