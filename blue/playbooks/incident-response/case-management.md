# Maintain a case that another analyst can continue

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

A lead warrants recorded analysis, or several workers need a common evidence and decision record. For an evidence-only answer with all inputs supplied, respect the bounded-task exception in AGENTS.md.

## Responsibilities

The owner agent controls intake and the consolidated report. A human incident owner makes business-risk decisions; a scribe can maintain records without becoming the decision maker.

## Work and decision records

1. Assign one case identifier and distinguish leads, incidents, tasks and related cases. Record scope, time bounds, source authority and urgency without embedding credentials.
2. Register evidence references with original location, collection time, hash where appropriate, handler and access restrictions. Store raw material privately; the case index should point to it.
3. Dispatch bounded questions with expected outputs, evidence references, required skill and finite-resource allocations. Each worker returns observations, uncertainty, failures and consumed resources.
4. Separate task status from incident status. A completed parser job does not close an unresolved incident, and an owner report does not imply every worker succeeded.
5. Record changes of scope and grants with issuer, action, resource, expiry and actual use. Existing applicable grants remain valid; do not repeatedly seek the same authorization.
6. At handover, list decisions pending, running consumers, leases, deadlines and next evidence checks. Release a resource only after its consumer has stopped.

## Completion evidence

A reviewer can trace the current assessment to evidence and understand all unfinished work. Close only when the defined analytical objective is satisfied or a named unresolved gap has a responsible owner. Produce the private message/token report separately from generic knowledge.

## Tabletop check

Exercise an analyst handover during a long query, a failed worker and a revised scope. Verify that the new owner neither duplicates expensive work nor loses an unresolved decision.

## Concrete observation contract

METIS's case helper (`metis journal`) stores material under `.metis-state/journal/{case}/`: `case.md` is the human-readable
summary, `timeline.jsonl` the action/evidence sequence, `queries.jsonl` the query record,
`findings.jsonl` the evidence-backed conclusions and `lessons.md` the review notes.
`raw/` and `work/` separate acquired inputs from working material. These private files
are distinct from the harness's `.state/state.sqlite3` run/task state; record a link between
case and run IDs when both are used rather than treating them as the same ledger.

For a query, retain dialect, exact bounded interval, parameters, source/version,
completion/partial state, result count and private output locator/digest. Each finding
needs enough evidence references to reconstruct its reasoning. Supplemental acquisition,
grant and handover fields may require case notes; the helper does not enforce every
workflow field automatically. Reconcile active consumers and outstanding decisions at
handover before another worker repeats an expensive or state-changing action.
