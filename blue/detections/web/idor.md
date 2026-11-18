# Verify object-level authorization with business context

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Was an authenticated principal permitted to access this particular object at the time of the request?

## Evidence to request

Principal and tenant identity, object identifier/type, historical ownership/sharing state, authorization decision, request outcome and classified response content.

## Reasoning procedure

- Compare access with the actual object policy, including delegated roles, tenant membership and explicit sharing. Numeric proximity of identifiers is not an authorization model.
- Use breadth or sequential access as a lead, then verify permissions for selected objects. Low-rate access to one sensitive object can still matter.
- Separate object lookup, authorization rejection, successful operation and returned protected content. A 200 response may be an error envelope.
- Preserve historical authorization state. Current permissions cannot automatically explain an earlier access.
- Keep read exposure distinct from modification or deletion; impact and response urgency differ.

## Alternatives and limits

Customer support, reporting, synchronization and administrators legitimately cross many objects. Shared accounts and incomplete ownership logs can prevent reliable attribution.

## Discriminating checks

Test owner access, explicitly shared objects, tenant mismatch, error responses using 200 and missing historical policy. A generic path-pattern rule cannot confirm this class. Do not enumerate other users objects to validate it.

## Concrete observation contract

Require server-side authorization instrumentation. A proposed local record includes
`actor_id`, `tenant_id`, `object_type`, `object_id`, `action`, `policy_version`,
`decision` and `outcome` with a request/trace reference. These are requirements to map
with the application owner, not columns supplied automatically by the SIEM. Preserve
the route-to-object transformation and the ownership/membership state at decision time.

Join the authorization decision to the actual read/write outcome for that same object
and actor. A route parameter change, HTTP 200, or a 404 deliberately masking a permission
decision cannot establish access alone. Cross-tenant identifiers must not collide in a
join. Fixtures should distinguish a valid shared object, a denied access and a confirmed
operation inconsistent with the applicable policy; do not enumerate live object IDs.
