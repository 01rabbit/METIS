# Investigate unusual directory discovery

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a principal collecting directory information outside its expected administrative or application role?

## Evidence to request

Directory query telemetry where configured, requester identity and source, query scope/attributes, object-access auditing, application inventories and network encryption coverage.

## Reasoning procedure

- Measure query breadth, requested attribute families and changes from the requester baseline. Volume alone overlooks low-rate exploration and flags legitimate synchronization.
- Use a stable account-plus-source context and distinct object/query counts. Paging and retries must not multiply a single enumeration into many independent acts.
- For decoy objects, verify that the decoy is not consumed by inventory, search indexing or normal administration before treating its access as high priority.
- Relate directory discovery to later access or permission changes without assuming that every broad reader is preparing an intrusion.

## Alternatives and limits

Identity synchronization, address books, asset inventory and directory management tools routinely read broadly. Encrypted directory traffic may expose connections without revealing queries; missing detailed auditing leaves a coverage gap.

## Discriminating checks

Test a scheduled directory sync, a new approved tool, a decoy accessed by indexing and unusual selective reads. Retain a separate count for logical queries and returned objects. Collection changes need directory-owner approval and a load budget.

## Concrete observation contract

Directory Services event 1644 from the Active Directory domain-service provider can
describe selected expensive, inefficient or long LDAP searches when the diagnostic
configuration enables them. It is not a complete LDAP request ledger. Retain client
address/port, starting node, filter, scope, visited/returned entries and search duration
as actually rendered by that version; do not assume illustrative SIEM aliases are raw
XML names. Paged searches and sync clients can create legitimate large counts.

Security 4662 offers different, SACL-dependent directory-object access evidence through
`ObjectType`, `Properties`, `AccessMask` and `SubjectLogonId`. Resolve attribute/right
identifiers and actor session rather than equating every directory read with enumeration.
Encrypted network traffic often lacks filter visibility. Document the selected source's
sampling/thresholds before deriving absence or query-volume conclusions.
