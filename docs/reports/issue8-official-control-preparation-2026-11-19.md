# Issue #8: official control preparation (2026-11-19)

## Result

Two user-authorized AlpacaHack Daily tasks now have answer-free local controls
and an observed official solve. This prepares candidate tasks for a controlled
comparison; **no MUNIN-on/off model comparison was run**. Neither task can be
counted as a fresh held-out performance trial after this preparation, because
its answer and method were exposed during the control work. Issue #8 remains
open.

| Task | Category | METIS run | Local control | Official observation |
| --- | --- | --- | --- | --- |
| `Flags for the FLAG` | Misc / Easy | `a90557e970e1419caf95019dfaf7681a` | One derived candidate accepted; a one-character mutation rejected | Browser submit: correct; `official_browser_observed`; run `solved` |
| `You are my friend` | Crypto / Easy | `f324a742e74e4f21bee2286bacacce65` | One derived candidate accepted; a one-character mutation rejected | Browser submit: correct; `official_browser_observed`; run `solved` |

Both positive and negative local checks ran in an isolated, network-disabled
sandbox without host mounts. The first task used the distributed Unicode
mapping; the second inverted the distributed ROT13 and chained XOR transform
and checked the result by forward transformation. These checks supported exact
candidate selection. The logged-in official AlpacaHack challenge pages then
showed a disabled `Solved` control after one submission per task. METIS recorded
`web attest` with `correct`, `official_browser_observed`, and final `solved` in
each run. The browser observations were made by a human operator; they are not
signed platform API verdicts. The two private per-problem write-ups retain the
methods and official verdicts without answer values.

## MUNIN starting state

Two answer-free technique cards were created from **different synthetic local
practice tasks**: an alphabetic rotation exercise and a standard Base64 text
exercise. Both source runs were classified `evaluation_split=practice` at
intake, locally verified before their cards were saved, and have card creation
times preceding the separate synthetic held-out plumbing run. That later run
froze both cards before work and retrieved the frozen copies under the source
provenance guard. These observations validate card creation, split labeling,
freeze order, and retrieval plumbing. They do not show that either card helps
solve the two AlpacaHack tasks, or that MUNIN improves performance. The cards,
source runs, and held-out plumbing run remain in private local state.

## Evidence boundary and next gate

The original distributions, protected exact-answer store, local oracle checks,
METIS ledgers, and write-ups remain private. The official pages and the
browser-observed verdicts provide stronger evidence than local format checks,
but the browser UI is not a signed or independently replayable API receipt.
Model pre-exposure and prior account solve history are not independently known.
Both tasks have the same Easy difficulty, so they do not supply a difficulty
stratum on their own.

Before a comparative study, select genuinely unseen tasks, fix the task list,
strata, solvability controls, answer isolation, arm definitions, model/runtime
versions, equal budgets, repetitions, randomization, and MUNIN snapshot timing.
Keep answer-bearing preparation material out of solver prompts and reusable
cards. Reconcile retained metrics against the controller ledger and report
unknown token or cost usage as unknown. No answer-rate difference, confidence
interval, latency/cost comparison, or ablation result is claimed here.
