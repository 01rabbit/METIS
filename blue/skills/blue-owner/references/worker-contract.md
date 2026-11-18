# Worker contract and completion checks

Use one compact assignment. Missing evidence is a valid outcome; a worker must not invent a
capability because the task names a parser or SIEM.

| Input | Include |
| --- | --- |
| Question | One decision or exact population; avoid “investigate everything” |
| Evidence | Allowed paths/IDs, digests if available, UTC interval and known acquisition gaps |
| Route | One specialist SKILL path and only the relevant reference paths |
| Resources | Run/task identity, acquired resource units, deadline and data/output limits |
| Authority | Allowed reads plus an existing grant's exact resource/action/scope; otherwise no external writes |
| Deliverable | Answer, evidence coordinates, contrary evidence, completeness and next action |

Return a concise result with status: supported, refuted, inconclusive or blocked.
For every substantive conclusion include the observed fields and a locator into the artifact.
Report tool unavailable, parse failed, cap reached and no matching event as distinct states.
A confidence label cannot replace those facts.

The owner verifies four things before synthesis:
- The result belongs to the current task, input digest and reservation, not an earlier attempt.
- The time and count model agree across workers, or the differences are explicitly explained.
- A negative conclusion has collection and parsing coverage; truncated output stays incomplete.
- Any external action is confirmed by its actual outcome, not a click or successful local send.

For bounded evidence-only questions, answer in the requested schema without creating case
state. For tool-using cases, use the real CLI commands in docs/runtime.md, always invoked as
metis blue from the repository root. A CLI model quota and a tool permission are separate
constraints. Claude CLI workers have a restricted tool set; a native worker may expose more.

When the assigned reference is insufficient, request a narrowly named missing artifact or
tool from the owner. Do not repeatedly retry an unavailable interface. Return enough context
for a fresh worker to continue without the full transcript.

Require the worker's source path, acquisition path/hash, record locator, selected field name,
raw value and derivation according to [evidence locators](../../soc-triage/references/evidence-locators.md).
Before accepting a result, reopen one consequential cited value and verify the actual column
and join rather than checking only that an artifact filename was provided. Missing source paths
stay unknown; a worker must not replace them with a handbook's example.
