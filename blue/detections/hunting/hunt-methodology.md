# Run a bounded hypothesis-led investigation

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

What specific uncertainty is this hunt meant to resolve, and what result would change the response?

## Evidence to request

An explicit scope, protected assets, behavioral hypothesis, required data, retention and query limits, owner and stopping conditions.

## Reasoning procedure

- Write both the expected suspicious observation and a plausible benign explanation. Identify the data that can distinguish them before issuing broad searches.
- Check data availability with small bounded queries. Ask the owner for finite query slots, time range or VM capacity before parallel work consumes shared resources.
- Iterate from a defined population to inspectable examples. Preserve query parameters, backend versions, page counts and deduplication assumptions.
- When evidence changes the hypothesis, record the change and re-evaluate earlier conclusions. Avoid selectively reporting only supportive searches.
- Close as supported concern, benign explanation, no supporting evidence within proven coverage, or unresolved due to a named gap. These outcomes have different follow-up work.

## Alternatives and limits

A hypothesis can be untestable with current data or resource limits. Empty results after a failed, timed-out or truncated query are not a negative finding.

## Discriminating checks

Tabletop a supported hypothesis, a benign counterexample, missing data and a depleted query budget. A reviewer should be able to reproduce the selection and understand why the hunt stopped. An owner must authorize any operational change that emerges.

## Concrete observation contract

Create a coverage row for each required source: provider/table/channel, event IDs or
action types, raw-to-normalized fields, observed interval, sensor/filter version and
eligible versus reporting assets. Record collection errors, query timeout, truncation,
pagination and access denial separately from zero matches. A source configured today
does not establish that last month's evidence was collected.

For each inert fixture, retain its identifier and digest, expected event membership,
entity relation and expected decision. Compare returned IDs and counts rather than
accepting a plausible-looking aggregate. State which step was tested: predicate,
backend execution or collection path. The [validation contract](../../skills/soc-detection-engineering/references/validation-integrity.md)
and raw telemetry references make this check repeatable without rerunning an intrusion.
The final hunt should report the unsearched population as well as the observed results.
