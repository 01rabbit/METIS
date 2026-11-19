# Issue #6 final-call handoff diagnostic result (2026-11-19)

The preregistered 30-cluster, three-arm real-model diagnostic completed all 90
scheduled runs. Each arm used the same task instances, model, eight-call shared
ceiling, two execution slots, private oracle, and bounded action policy. The
two multi-specialist arms also had the same four-call ceiling per specialist.
The retained data contain metrics only; no candidate, answer, prompt, oracle
digest, or raw model message is included.

| Arm | Workflow complete and oracle verified | Raw oracle verified | Mean calls | Mean elapsed |
| --- | ---: | ---: | ---: | ---: |
| Single specialist | 28/30 | 28/30 | 5.83 | 39.59 s |
| Two specialists, combined handoff | 18/30 | 20/30 | 7.43 | 30.37 s |
| Two specialists, final-call handoff | 13/30 | 16/30 | 7.83 | 31.34 s |

The preregistered primary contrast, final-call handoff minus single
specialist, was **−0.50** on workflow-complete, oracle-verified tasks. The
paired 10,000-resample cluster bootstrap 95% interval was **[−0.6667,
−0.3333]**. The gain condition for Issue #6 was not met. The narrower
final-call versus current combined multi-specialist contrast was **−0.1667**
with interval **[−0.3667, 0.0333]**. The final-call schema increased workflow
completion alone to 23/30 versus 21/30, but fewer of those completions were
oracle correct. Completion alone is not the acceptance metric.

The final-call arm had seven jobs failing at a candidate-ready shared-call
ceiling, six candidate-ready specialist-call ceiling failures, and seven
report rejections. The current multi arm had six, four, and ten respectively.
These mechanisms do not explain away the negative primary result. Mean input
tokens were 83,686 for final-call, 79,342 for current multi, and 62,873 for
single. Provider cost was unavailable and is reported as unknown.

The analyzer checked all 30 task clusters and complete arm sets against the
frozen order. The metrics JSON and analysis JSON are under `reports/data/`.
The experiment uses synthetic encoding tasks with one trial per cluster; it
does not establish performance on general CTF challenges. This is a negative
result for this bounded design, so Issue #6 and its dependent Issue #7 remain
open. A new hypothesis and separately preregistered study would be required
before claiming measured multi-specialist improvement.
