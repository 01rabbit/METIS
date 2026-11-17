# Issue #6 candidate/report handoff diagnostic (2026-11-18)

## Result

The preregistered diagnostic completed all 90 arm-runs over 30 newly generated
synthetic encoding-task clusters. The protected oracle confirmed 27/30 single,
23/30 multi-separate, and 21/30 multi-combined candidates. Under the preregistered
workflow-complete-and-oracle-verified outcome, the counts were 27/30 (90.0%),
8/30 (26.7%), and 19/30 (63.3%), respectively.

The primary contrast was multi-combined minus single: −26.67 percentage points,
with a paired task-cluster bootstrap 95% interval of [−43.33, −13.33] points.
The preregistered gain gate is not met. In paired outcomes, combined and single
both passed on 19 clusters; only single passed on 8; only combined passed on 0;
neither passed on 3.

The workflow-completion contrast, multi-combined minus multi-separate, was
+43.33 points ([+20.00, +66.67]). The raw oracle-correctness contrast was
−6.67 points ([−23.33, +10.00]); it is not an improvement. The combined
workflow-complete-and-verified contrast was +36.67 points ([+13.33, +56.67]).
Six clusters passed that combined outcome in both arms, combined alone passed on
13, separate alone on 2, and neither on 9.

Combined averaged 7.367 reserved calls versus 8.000 for separate and had 6
versus 20 candidate-ready call-ceiling failures. However, combined had 11
report rejections versus 9 and two fewer raw oracle hits (21 versus 23). Thus,
the preregistered full handoff-support rule is not met: fewer total calls and
candidate-ready ceiling failures coexist with more report rejections and no
raw-correctness improvement. Total calls are only a proxy and do not isolate
handoff-related calls. This is narrow evidence that the combined arm completed
more workflows, not proof that call starvation caused the historical result.

## Interpretation and limits

This diagnostic used one trial per task cluster and synthetic encoding tasks.
It does not establish general CTF or AlpacaHack performance. Its combined
handoff treatment includes report timing and retry behavior as well as a possible
saved call. Provider cost is unknown. The complete answer-free 90-run dataset,
deterministic analysis output, frozen preregistration, runner, and analyzer are
retained alongside this report. The analyzer checks case-to-cluster and cached
per-arm metric consistency before producing paired completion-only, raw
correctness, and combined outcomes.

The measured-gain acceptance gate for Issue #6 remains unmet. Issue #6 and its
dependent Issue #7 remain open; no issue is closed by this result.

## Reproduction

```sh
.venv/bin/python scripts/run_issue6_handoff_diagnostic.py
.venv/bin/python -m metis.evaluation.issue6_handoff_diagnostic \
  docs/reports/data/issue6-handoff-diagnostic-2026-11-18.json > \
  docs/reports/data/issue6-handoff-diagnostic-analysis-2026-11-18.json
```

The runner refuses to overwrite the retained dataset. The command above is
provided for provenance; use a new preregistered output path and task seed for a
replication.
