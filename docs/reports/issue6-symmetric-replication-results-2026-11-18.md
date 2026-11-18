# Issue #6 symmetric real-model replication (2026-11-18)

## Result

The preregistered 120 arm-runs completed across 30 seeded task clusters and two
paired repetitions per task. Candidate composition and protected-oracle
verification were performed by the same Daybreak code path for both arms.
The single-specialist arm completed all 60 workflows and produced 56
oracle-verified answers (93.3%). The two-specialist arm completed only 16/60
workflows; 11 were both workflow-complete and oracle-verified (18.3%). Its
remaining 44/60 workflows had at least one failed specialist job. The multi
arm had 20 trials with both jobs failed, 16 with one failed, and 8 with one
failed and one completed (assignment order is immaterial). Only 16 trials had
both jobs complete.

The primary paired, workflow-complete solve-rate difference (multi minus
single) was **-75.0 percentage points**, with a 95% task-cluster bootstrap
percentile interval of **[-86.67, -61.67] points**. Across all oracle
candidate checks, including incomplete workflows, the difference was -20.0
points (95% cluster interval [-31.67, -8.33]); this is diagnostic only because
partial workflows score zero under the registered completion rule. The
protocol-complete paired outcomes were 11 both, 45 single-only, 4 neither,
and 0 multi-only.

The multi-specialist arm was faster: mean end-to-end time was 26.169 seconds
versus 43.281 seconds for single, a single-minus-multi paired difference of
17.112 seconds (95% task-cluster interval [15.3234, 18.9947]). That speed
came with materially lower workflow completion and accuracy. It used all 8
model-call and all 4 mediated-action slots in every trial. Single averaged
6.733 observed calls and also used all 4 actions. All 120 runs reported token
usage; mean input tokens were 82,213.2 multi versus 70,458.2 single, and mean
output tokens were 798.3 versus 789.9. Provider cost was unavailable.

## Acceptance decision

This evidence does **not** satisfy Issue #6's paired-gain criterion for
multi-specialist decomposition. Keep #6 open. It also does not satisfy a
positive paired gain that could support dependent P6 acceptance; do not treat
this as completing P6 or closing any dependent issue. The principal failure
mode was orchestration/job completion in the multi arm, so the result is a
real measurement of the current end-to-end METIS/Codex workflow, not a clean
estimate of specialist reasoning quality when both jobs finish. A future
experiment can investigate that reliability issue, but this fixed study is
complete and must not be selectively rerun or recoded.

## Method and limits

The frozen protocol is
[`issue6-symmetric-replication-preregistration-2026-11-18.md`](issue6-symmetric-replication-preregistration-2026-11-18.md).
Codex CLI `0.169.0`, model `gpt-6.1-sol`, low reasoning, and METIS memory
retrieval disabled were used. Both arms returned only intermediate components
through private candidate storage. Daybreak parsed those components, composed
the digest, and queried the same protected local fixture oracle. The raw
answer-free trial dataset preserves task/arm IDs, run IDs, oracle booleans,
workflow state, usage, and resource counts. It contains no component bytes,
candidate values or paths, digests, or oracle values. The oracle and temporary
solver roots were removed when execution exited normally.

The 95% intervals use 10,000 paired bootstrap samples, resampling the 30 task
clusters and retaining both repetitions. This is a synthetic short-text
encoding set and cannot establish general CTF performance, AlpacaHack solve
rate, held-out P7 performance, provider cost, or BridgeHost-native budget
enforcement. The comparison is between the full one- and two-specialist
workflows, including orchestration reliability and role-prompt differences.

## Reproducibility artifacts

- Frozen design: [`issue6-symmetric-replication-preregistration-2026-11-18.md`](issue6-symmetric-replication-preregistration-2026-11-18.md)
- Runner: [`run_issue6_symmetric_replication.py`](../../scripts/run_issue6_symmetric_replication.py)
- Answer-free per-arm dataset: [`issue6-symmetric-replication-2026-11-18.json`](data/issue6-symmetric-replication-2026-11-18.json)
- Paired analysis: [`issue6-symmetric-replication-analysis-2026-11-18.json`](data/issue6-symmetric-replication-analysis-2026-11-18.json)
- Analyzer: [`issue6_diverse_analysis.py`](../../src/metis/evaluation/issue6_diverse_analysis.py)
