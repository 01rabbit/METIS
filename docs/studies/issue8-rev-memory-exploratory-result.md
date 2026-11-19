# Issue #8 Rev memory comparison: exploratory result

Protocol SHA-256: `2204980da039f6716451a59817069ffeb743977e293e40811a8cd455426bc5bb`

The preregistered eight held-out runs completed on 2026-11-19. The two official
AlpacaHack distributions and the independent protected local answer controls
passed preflight before any held-out model call. The candidate answers and
private controller database remain outside Git. No official answer was submitted.

| Task | Repetition | Arm | Calls | Tokens | Outcome |
| --- | ---: | --- | ---: | ---: | --- |
| misdirection | 0 | full | 6 | 77,507 | incomplete |
| misdirection | 0 | without_memory | 6 | 75,514 | incomplete |
| misdirection | 1 | full | 6 | 77,484 | incomplete |
| misdirection | 1 | without_memory | 6 | 75,521 | incomplete |
| read-a-binary | 0 | without_memory | 6 | 75,201 | incomplete |
| read-a-binary | 0 | full | 6 | 77,720 | incomplete |
| read-a-binary | 1 | full | 6 | 77,152 | incomplete |
| read-a-binary | 1 | without_memory | 6 | 75,238 | incomplete |

All 24 specialist jobs ended with `run specialist model-turn budget exhausted`.
No run produced a candidate. Total reserved model turns were 48 of the 50-call
study cap; recorded run time totaled 106.98 seconds of the 7,200-second cap.
All eight runs exceeded the declared 50,000-token per-run budget. The current
controller records token usage but does not enforce that limit, so the study
has eight resource-ineligible, incomplete trials. Its cost is unknown.

Both tasks were preregistered with prior model exposure `unknown`. The evaluator
therefore excluded all eight runs from acceptance-eligible solve counts. The
observed zero candidate rate does not establish that memory helps or hurts;
the fixed six-call limit and token overrun prevent a performance conclusion.
Issue #8 remains open. A further trial needs a new protocol, token enforcement,
and a budget compatible with the delegated specialist workflow. Those conditions
must be fixed before another model attempt; these results must remain separate.

The historical runner now verifies the saved schedule, unique run bindings,
held-out session records, audit chains, terminal job states, model-call
reservations, candidate state, stop reasons, frozen memory, and arm dispatch
before accepting a saved run. This protocol is closed to new model calls
because its declared token cap was not enforced. A new comparison requires a
new preregistered protocol with an effective token control; editing the old
progress file cannot reopen this study.

The private, answer-free controller records are at
`/private/tmp/metis-issue8-study-run/`. The public report omits candidate
answers, oracle digests, and private ledger content.
