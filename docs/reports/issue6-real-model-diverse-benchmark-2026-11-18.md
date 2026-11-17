# Issue #6 diverse real-model paired benchmark (2026-11-18)

## Result

The preregistered two-specialist arm improved workflow-complete oracle solves
on this bounded synthetic task set. It completed 12/60 runs with an oracle-
verified answer (20%); the single-specialist arm completed 0/60 (0%). The
paired difference was **+20.0 percentage points**, with a 95% task-cluster
bootstrap percentile interval of **[+10.0, +30.0] points**. The interval
resampled the 30 task IDs 10,000 times with seed `20261118`, retaining both
repetitions per sampled task.

The oracle alone accepted a candidate in 53/60 two-specialist runs (88.3%) and
0/60 single-specialist runs. However, **41 of those 53 multi-arm candidates
came from runs where the assigned jobs or synthesis did not complete**. These
are diagnostic oracle hits, not completed solves, and are scored as zero under
the preregistered rule. The two-specialist workflow itself completed only
15/60 trials; 12 of those were oracle-correct. All 60 single-specialist runs
completed their workflow, with no correct answers. This distinction is
material to the result.

Among paired task repetitions, 12 were multi-only workflow-complete solves and
48 had neither arm solve; there were no single-only solves. The separately
reported raw-oracle discordance was 53 multi-only and 7 neither.

The multi-specialist arm averaged 28.9 seconds end-to-end, 8.0 observed model
calls reserved/observed (99.8% of the eight-call cap), 4.0 mediated actions,
82,430 reported input tokens (54,144 cached), 828 output tokens, and 175
reasoning-output tokens. The single-specialist arm averaged 42.7 seconds,
6.05 calls reserved/observed (75.6% of cap), 4.0 actions, 63,197 input tokens
(39,913 cached), 736 output tokens, and 100 reasoning-output tokens. The
multi-specialist workflow was incomplete in 45/60 trials. The paired latency
difference (single minus multi) was 13.752 seconds, with a 95% task-cluster
bootstrap interval of [12.318, 15.258] seconds. Monetary provider cost was
unavailable. Token figures are runner-reported aggregates.

## Method and limits

The evaluation followed the frozen design in
[`issue6-real-model-diverse-preregistration-2026-11-17.md`](issue6-real-model-diverse-preregistration-2026-11-17.md)
with Codex CLI `0.169.0`, `gpt-6.1-sol`, low reasoning, and MUNIN retrieval
disabled. It used 30 distinct synthetic decoding tasks, 60 task repetitions,
and 120 total arm runs under matched aggregate call, action, slot, and wall
budgets. The private oracle was outside run artifact roots. The final aggregate
contains task identifiers and metrics only; the private oracle was removed
after the run. No candidate, component plaintext, digest, answer, or candidate
path is included in this report.

This supports a paired gain for this particular synthetic short-text decoding
set under the tested Codex CLI controller. It does not establish general CTF
performance, AlpacaHack solve rate, P7 held-out performance, or BridgeHost
budget enforcement. The two-arm contrast bundles role prompts and task
decomposition. Multi-arm job failures were frequent and materially reduced
workflow completion. Issue #6 can be considered met for its preregistered
paired-gain gate, while these reliability limits remain explicit; broader P6
and issue #7 acceptance still require their own evidence.

The aggregate analyzer is
[`issue6_diverse_analysis.py`](../../src/metis/evaluation/issue6_diverse_analysis.py);
its tests are in [`test_issue6_benchmark_analysis.py`](../../tests/test_issue6_benchmark_analysis.py).
