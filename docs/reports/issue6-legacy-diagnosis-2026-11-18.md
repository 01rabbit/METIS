# Issue #6 frozen replication diagnosis (2026-11-18)

The deterministic analyzer `python -m metis.evaluation.issue6_legacy_diagnostic`
reads only the retained answer-free replication JSON. It does not rerun tasks,
read private artifacts, or infer missing event records.

| Arm (60 trials each) | Oracle correct, any workflow | Report complete | Complete and oracle correct | Oracle correct but incomplete | Incomplete at eight reserved calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single | 56 | 60 | 56 | 0 | 0 |
| Two specialists | 44 | 16 | 11 | 33 | 44 |

The multi arm had 16 two-job completions, 24 trials with one failed job, and
20 with two failed jobs. Of its 16 complete workflows, five were oracle
incorrect. All 60 multi trials reserved eight calls. The retained records
do not say whether a candidate was ready when a job failed, whether a
candidate/report handoff failed, or whether a further model turn was denied.
These are **unobserved mechanisms**, not zero counts or established causes.

The [prospective handoff diagnostic preregistration](issue6-handoff-diagnostic-preregistration-2026-11-18.md)
uses unused task clusters, symmetric final composition and protected oracle,
and the same eight-call, four-action, two-slot and 600-second run caps. It
specifies the event counters needed to distinguish candidate-ready failures,
report rejection, and model-turn budget denial. Its primary gain gate is the
paired, workflow-complete oracle result against the single arm. This legacy
diagnosis does not alter the negative replication result or establish a gain.
