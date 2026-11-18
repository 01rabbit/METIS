# Coordinate investigation, protection and recovery as overlapping work

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

An incident requires more than one analytical or operational activity and needs explicit progress decisions.

## Responsibilities

The incident owner coordinates workstreams. Evidence, service, identity, communication and business owners remain responsible for their respective decisions.

## Work and decision records

1. Prepare scope, authority, contact paths and a private case record. Confirm usable telemetry and resource constraints instead of assuming readiness.
2. Investigate and assess impact while considering immediate protective actions. Full attribution or final scope is not a prerequisite for proportionate authorized containment.
3. Record containment choices, verification and remaining paths. Continue hunting and adjust scope while controls are in effect.
4. Remove demonstrated access paths and correct underlying weaknesses through approved changes. If new affected systems appear, feed them back into investigation and containment.
5. Restore service under explicit acceptance criteria, monitoring and rollback. Availability, data integrity and restored trust require separate checks.
6. Close the incident with evidence-based conclusions and assigned residual work. Review failures and successful controls, then verify the resulting improvements.

## Completion evidence

Each workstream has a current owner, next decision and evidence required to progress. The case may loop between activities rather than following a rigid waterfall.

## Tabletop check

Tabletop scope expansion during recovery and ongoing harm during incomplete acquisition. Confirm that the process revisits earlier decisions instead of treating phase completion as irreversible.

## Concrete observation contract

Define milestone fields before measuring response time: first supported observable,
detection, incident declaration, first verified containment, scope bounded, eradication
accepted, recovery accepted and closure. Keep UTC time, source locator, whether the
value is observed or estimated, and any uncertainty interval. An unknown start time is
not zero dwell time. Recording time and event time are different values.

Maintain concurrent work tracks for evidence, containment, impact, communication and
recovery, with dependencies and the authority needed for each transition. A containment
API acknowledgement does not fill the verified-containment milestone; record the
independent observed effect. Reopened scope should preserve previous assessments and
their reasons. Recovery can proceed for a verified bounded service while another scope
remains unresolved, provided the responsible owner accepts the documented residual risk.
