# Turn an alert into a defensible incident decision

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

An automated alert, user report or investigator observation needs triage and possibly incident declaration.

## Responsibilities

Tier 1 verifies the signal and gathers context. The owner routes specialized analysis, reserves shared resources and escalates impact decisions to the incident owner.

## Work and decision records

1. Recover the original observation and confirm the detector/provider, entity, timestamp and collection health. A dashboard label is a lead, not the underlying evidence.
2. Identify the concrete claim and its required evidence. Distinguish attempted behavior, successful action, control weakness and confirmed impact.
3. Check the most plausible benign alternative and a small number of decisive pivots. Prefer bounded high-information queries to parallel broad searches on constrained SIEM capacity.
4. Estimate affected assets, identities, data and ongoing activity. Mark confirmed, suspected and not-assessed populations separately.
5. Assign severity from impact, urgency and confidence using the local escalation policy. A low-confidence signal on a critical asset may still justify urgent review.
6. Declare, continue investigating, or close the lead with the supporting evidence and explicit remaining gaps. Credible ongoing harm may need containment before all analysis finishes.

## Completion evidence

Another analyst can explain why the lead was escalated or closed and which event-level facts support that choice. Incomplete coverage is preserved as a limitation rather than converted into a clean bill of health.

## Tabletop check

Exercise a benign administration alert, an incomplete parser result, a false dashboard duplicate and an urgent partially scoped incident. Check that no single heuristic is silently promoted into proof.

## Concrete observation contract

Register the alert with rule ID/version/digest, source query, search interval, result
completeness and original evidence locators. For Windows records, preserve originating
host, provider, channel, event ID/version, `EventRecordID`, event UTC time and ingestion
time. The domain controller that emitted an authentication record may not be the source
workstation, so keep actor, emitting host and target as separate entities.

Map normalized fields back to those raw records and verify required collection settings
before interpreting a negative result. Record each proposition as observed, inferred or
unknown, with the missing evidence needed to change it. The resulting decision can be
incident, evidence-supported benign activity or unresolved; an executed query and a
closed worker task do not force a definitive incident verdict. Repeated collector rows
must not be counted as repeated independent actions.
