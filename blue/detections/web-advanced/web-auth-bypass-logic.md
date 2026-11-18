# Verify that protected actions have the required authorization history

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a protected operation occur without the prerequisite authentication, authorization or workflow decision?

## Evidence to request

Application state-machine/policy definition, request/session/action IDs, authoritative decision logs, clock/delivery bounds and protected-operation outcome.

## Reasoning procedure

- Define the exact prerequisite and where it is logged. A missing predecessor is meaningful only when that source is complete for the relevant interval and entity.
- Use server-side identity and workflow state rather than client-supplied claims. A request header or URL parameter is not authoritative authorization.
- Separate replay, skipped workflow steps, role confusion and stale session use; each needs a different relationship between events.
- Perform missing-event comparisons with a justified delay window and deduplicated keys. Asynchronous logs can make a valid predecessor appear absent.
- Require an actual protected effect before asserting successful bypass, and keep incomplete history as unresolved.

## Alternatives and limits

Federated authentication, long-lived sessions, service accounts and asynchronous workflows can have valid decisions outside a narrow search. Changes to application logging can silently break anti-joins.

## Discriminating checks

Test delayed predecessors, incomplete log coverage, a legitimate delegated role, duplicate actions and an attributable missing authorization decision. Do not exercise forbidden workflows against a live service. Fixes need a reviewed application change.

## Concrete observation contract

Define a server-owned workflow/transaction ID and record principal, session reference,
step, authorization-policy version, before/after state and protected-operation outcome.
These local application fields must be confirmed, not presumed to exist in access logs.
The request order should be interpreted against server state, not just browser navigation
or endpoint names.

An apparently missing prerequisite can be outside the search interval, retained in
another service or absent because of collector loss. A negative join is meaningful
only with complete coverage of the relevant workflow and identity. Distinguish a
legitimate resumed workflow, a rejected out-of-order request and an unauthorized state
transition that actually completed. A success-looking response or continued prior
session does not establish that a new authentication/authorization check was bypassed.
