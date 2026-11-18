# Build an evidence graph across investigation stages

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Do several observations belong to the same activity chain, or have unrelated events been merged into a narrative?

## Evidence to request

Original event identifiers, entities and timestamps; host boot/process identities; file hashes; account/session bindings; network/request IDs; uncertainty and clock estimates.

## Reasoning procedure

- Choose an explicit join for every edge: process to child, file to executed image, session to action, or request to backend event. Host-plus-time alone is a weak association.
- Keep observed order separate from arrival order. Late forwarding can reorder an apparent sequence; specify tolerated delay and clock uncertainty.
- Avoid multiplying one event across many joins. Report component event counts, distinct entities and matched chains independently.
- Do not require every phase of a named lifecycle. Partial visibility can still justify response, while a complete-looking chain can still be benign.
- Show alternative edges and unresolved breaks instead of silently replacing gaps with a likely story.

## Alternatives and limits

Installers, fleet-management tasks and scheduled operations can combine file writes, execution, service changes and network activity. Shared service identities make host-wide grouping particularly misleading.

## Discriminating checks

Test a genuine inert sequence, interleaved unrelated workflows, duplicate components, reversed arrival order and a missing stage. A stronger severity must derive from evidenced impact and confidence, not merely the number of joined labels.

## Concrete observation contract

Maintain an entity table before correlating stages. Windows `Computer` identifies the
event-emitting machine, which may be a domain controller rather than the source endpoint.
`IpAddress` and destination/service fields can refer to other entities. Use host plus
process GUID or PID/creation-time for execution, and destination host plus logon context
for `LogonId`. A directory object's GUID is not the actor's process identifier.

Deduplicate retained Windows records by originating host, provider, channel and
`EventRecordID`, with collection/reset context; do not use the event number as a row ID.
For each stage edge, state the relation and maximum interval explicitly, including clock
uncertainty. A service registration, ticket request and later process may remain three
separate leads when their identifiers do not bind. Include partial chains and conflicting
host attribution in fixtures, not only a neat complete timeline.
