# Issue #6 dynamic borrowing feasibility pilot results

The frozen [preregistration](issue6-borrow-pilot-preregistration-2026-11-18.md)
was committed as `b0ffa019eff76aa01c24aef6e0c045335675b8f6` before model calls.
The runner was committed as `4c46dbbb8ebe7d8d1d3dd5d8b7082028ed9ff591`
before execution. Codex CLI `0.169.0` matched the pin; the model was
`gpt-6.1-sol` with low reasoning and memory retrieval disabled. All 18 arms
completed once on six new synthetic task clusters. No task was replaced or
rerun. Final SHA-256 composition and oracle checks stayed in the controller.

| Arm | Raw oracle correct | Workflow complete | Both complete and correct | Mean calls | Mean seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single | 5/6 | 6/6 | 5/6 | 5.833 | 42.221 |
| Multi fixed | 3/6 | 2/6 | 1/6 | 7.833 | 33.068 |
| Multi borrow | 4/6 | 3/6 | 3/6 | 7.833 | 33.508 |

The preregistered primary `multi_borrow - single` contrast was **−2/6**
(−33.33 percentage points), with a descriptive six-cluster task bootstrap
95% interval [−66.67, 0.00] points. Paired outcomes were three both, zero
borrow-only, two single-only and one neither. `multi_borrow - multi_fixed` was
+2/6 (+33.33 points), interval [0.00, 66.67]. This suggests that borrowing
helped the fixed multi arm on these tasks, but it did not produce a win over
single. The registered negative-primary stop applies; no larger study or
rerun follows from this pilot. Issue #6's measured-gain gate remains unmet.

Both multi arms reserved an average 7.833 calls. The borrow arm had zero
`model_turn_budget_exhausted` events versus five for fixed, but four
`model_turn_peer_reserve` events under its first-call fairness rule. It still had
three candidate-ready workflows failing at the call ceiling, five report
rejections and four jobs ending in the call/turn-limit category. These data
do not isolate a single cause. Six synthetic tasks do not establish general
CTF performance, and provider cost was unavailable.

The [answer-free trial records](data/issue6-borrow-pilot-2026-11-18.json) and
[deterministic analysis](data/issue6-borrow-pilot-analysis-2026-11-18.json)
contain no component, candidate, digest, oracle value or raw model output.
A recursive key audit found only task identifiers, states, counts, times and
usage fields; a 64-hex scan and private-path scan found none. Temporary
artifacts and oracle data were removed on normal exit.
