# Issue #6 action-reserved conditional delegation pilot: results

The [corrected preregistration](issue6-conditional-reserve-pilot-preregistration-2026-11-18.md),
runner, analyzer, and action-reservation integration test were committed and
pushed as `37f6dd1` before the corrected study's first model call. All 24
arms ran once in the frozen seeded order on twelve new synthetic clusters.
No task was replaced or rerun. Codex CLI `0.169.0` matched the pin; the model
was `gpt-6.1-sol` with low reasoning and memory retrieval disabled. Every run
used the `practice` split, identical controller-side SHA-256 composition, and
the protected local oracle.

| Arm | Workflow-complete verified | Raw oracle correct | Mean reserved calls | Mean actions | Mean seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single | 12/12 | 12/12 | 5.667 | 4.000 | 40.732 |
| Conditional | 11/12 | 11/12 | 3.500 | 2.333 | 41.787 |

The preregistered conditional-minus-single primary difference is **−1/12**
(−8.33 percentage points), with descriptive task-cluster bootstrap 95%
interval [−25.00, 0.00] points. Paired outcomes include zero conditional-only
and one single-only completion. Two conditional runs dispatched the forensics
fallback; both had completed lead and fallback jobs and verified outcomes.
The conditional arm did not improve the primary outcome. The registered
nonpositive stop applies: no larger or held-out replication follows from this
pilot, and Issue #6's measured-gain gate remains unmet.

Both arms had zero report rejections and zero model-turn budget denials.
Token usage was reported for all arms: single used 726,185 input and 8,660
output tokens in total; conditional used 442,154 input and 12,417 output
tokens. Provider dollar cost remained unavailable. These twelve simple
synthetic clusters do not estimate general CTF performance; the fallback
triggered only twice, so the trial provides limited evidence about its effect.
The first conditional pilot's nine retained records are separately documented
as an aborted design, not combined with this result.

The [answer-free trial records](data/issue6-conditional-reserve-pilot-2026-11-18.json)
and [deterministic analysis](data/issue6-conditional-reserve-pilot-analysis-2026-11-18.json)
contain no components, candidate values, digests, oracle answers, raw model
output, or private paths. A recursive key audit and scans for absolute private
paths and 64-hex values found none. Temporary run and oracle directories were
removed on normal exit. The final file was published only after all 24 unique
case-arm records were present; interruption checkpoints used `.partial.json`.

## Review follow-up (2026-11-19)

The analyzer now rejects mismatched task counts, unreserved or over-budget
model calls, fabricated dollar costs, and incomplete or impossible token
accounting when usage is marked complete. The retained analysis explicitly
marks provider dollar cost as unknown and original model transcript attestation
as unavailable. This strengthens checks of the answer-free metrics; it cannot
reconstruct deleted transcripts or independently prove what the provider
returned. The registered nonpositive stop remains in force. Any new policy
would require its own preregistration and independent held-out evaluation;
these records are not reused as held-out acceptance evidence.
