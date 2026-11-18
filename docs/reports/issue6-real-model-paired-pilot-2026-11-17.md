# Issue #6 real-model paired pilot (2026-11-17)

## Scope

This is one paired observation using the local Codex CLI through METIS's
production `AgentScheduler`, `autopilot`, tool-intent, private-candidate, and
local commitment-verifier paths. It is a synthetic Base64 fixture, not an
AlpacaHack problem or held-out evaluation. The provider ran with Codex CLI
0.169.0 under the required macOS Seatbelt isolation. The model ID was not
explicitly selected or captured, so this report calls it the CLI default.

The same seeded artifact and private SHA-256 commitment were used in both
arms. Each run had a shared cap of eight model calls, four mediated artifact
actions, two scheduler slots, and 600 seconds. The single arm assigned one
crypto specialist to the task. The multi arm assigned a crypto specialist and
an artifact-triage specialist to solve the same task independently. Candidate
values were kept in the temporary private candidate directory and are not
included here.

## Observation

| Measure | One specialist | Two specialists |
| --- | ---: | ---: |
| Locally verified candidates | 1/1 | 1/1 |
| Provider calls used | 3 | 6 |
| Artifact actions used | 1 | 2 |
| Input tokens | 29,881 | 59,627 |
| Cached input tokens | 0 | 6,784 |
| Output tokens | 265 | 539 |
| Reasoning output tokens | 0 | 15 |
| Elapsed seconds | 20.95 | 21.83 |

Both runs produced a candidate that passed the controller's private local
commitment verifier. The two-specialist arm was 0.88 seconds slower and used
twice as many provider calls and almost twice the reported input tokens. The
extra specialist did not improve this duplicated, one-step task.

## Limits and next gate

This is one pair, so it cannot support an estimate or confidence interval for
general model performance. The fixture is intentionally mechanical, both
specialists received the same artifact, and the model ID was not pinned. It
does show that real Codex model calls, controller intents, private candidates,
shared call reservations, and independent verification can be measured through
METIS. The experiment does not demonstrate a multi-agent gain; Issue #6 remains
open pending a pre-registered set of diverse tasks, a pinned model, repeated
matched runs, uncertainty estimates, and latency/cost reporting. Dollar cost
was not available from the provider.
