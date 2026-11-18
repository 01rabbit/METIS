# Issue #6 six-cluster feasibility pilot results (2026-11-18)

The [frozen preregistration](issue6-feasibility-pilot-preregistration-2026-11-18.md)
preceded all model calls. Codex CLI `0.169.0` matched the pin. All 18 arm-runs
completed across six new `pilot6-*` task IDs. No task was added, replaced, or
rerun. The existing runner composed the final digest from private components
and queried the same protected oracle for every arm.

| Arm | Oracle correct, any workflow | Workflow complete | Both complete and correct | Mean calls | Mean seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single | 4/6 | 6/6 | 4/6 | 6.000 | 45.193 |
| Multi separate | 5/6 | 2/6 | 2/6 | 8.000 | 27.113 |
| Multi combined | 4/6 | 4/6 | 2/6 | 7.667 | 28.584 |

The primary paired multi-combined minus single difference was **−2/6**
(−33.33 percentage points). The descriptive six-cluster bootstrap 95% interval
was [−83.33, +33.33] points. Paired outcomes were one both, one combined only,
three single only, and one neither. The pilot is negative under its primary
rule, so the registered stopping rule ends this line without extension or
rerunning failures. Six synthetic clusters cannot establish a measured gain or
general CTF performance.

Combined versus separate had the same complete-and-correct count (2/6 each).
Combined completed more workflows (4 versus 2), but had fewer raw oracle hits
(4 versus 5) and three report rejections versus zero. Candidate-ready
call-ceiling failures were two versus four; model-turn budget denials were two
versus five. These observations do not isolate handoff as the cause of the
earlier negative result.

## Classification correction and data handling

The model calls ran from runner commit `8e260db` after preregistration commit
`f0c6f72`. Result commit `2f22eaf` later changed the committed runner:
it set the pilot wrapper's `EVALUATION_SPLIT` to `unlisted` and added the
pilot identity/seed/task-family checks to `analyze()`. Those post-run changes
were not part of the executed script and cannot be treated as preregistered
controls. The retained output and the analysis produced from it are unchanged.

The running pilot inherited `evaluation_split="heldout"` in its temporary
METIS session metadata from the diagnostic runner. That was a labeling error:
the preregistered six-cluster work is a feasibility pilot, **not** a held-out
acceptance result. The metadata was in a temporary database, not the retained
answer-free JSON. After the run, the runner was parameterized and its pilot
wrapper set to `unlisted`; this does not retroactively change the executed
sessions. The occupied output path prevents rerunning this pilot.

The retained 18-record JSON contains task IDs, encoding-family names, arm
order, booleans, states, counts, times, aggregate token usage, and action
names. A recursive key audit found no component, plaintext, digest, flag,
candidate value/path, oracle value, artifact path, or raw message fields; a
64-hex-string scan found none. The key `candidate` occurs only as a countable
decision-action name. Temporary private artifact and oracle roots were removed
on normal exit. Provider cost remains unknown.

Dataset: [answer-free trial metrics](data/issue6-feasibility-pilot-2026-11-18.json).
Analysis: [deterministic summary](data/issue6-feasibility-pilot-analysis-2026-11-18.json).

Review follow-up: the generic `analyze()` now receives optional `StudyShape`
data for identity, seeds, task IDs and encoding-pair counts. The CLI selects
the frozen pilot shape outside the analysis function; other studies can supply
their own shape without adding study-specific branches inside `analyze()`.
The retained dataset and numerical result have not changed.
