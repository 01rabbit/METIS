# Choose containment while uncertainty remains

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

Observed or credible ongoing harm justifies reducing access or propagation, even if the full scope is still being investigated.

## Responsibilities

The incident owner coordinates the decision. The asset/business owner supplies impact and continuity constraints. Operational execution requires an applicable user authorization or scoped owner grant.

## Work and decision records

1. State the harm to reduce, the affected resources, the urgency and the cost of delay. Compare options such as network isolation, access restriction, session revocation or temporary service controls.
2. Evaluate dependencies and safety: shared hosts, identity infrastructure, critical services and industrial processes may be harmed by broad isolation. Prefer the narrow effective action when feasible.
3. Decide whether to preserve volatile evidence before acting. Balance acquisition time and side effects against continuing harm; evidence capture must not become an automatic reason to delay urgent protection.
4. Prepare the exact action, expected effect, rollback, verification and authority reference. Existing matching grants suffice; broadened resources or actions require the owner to resolve authority.
5. Execute only the approved action, record observed results and verify that the intended traffic/session/access is actually constrained. A successful API response is not complete operational verification.
6. Continue scoping and revisit the containment boundary as new evidence arrives. Explain any temporary service risk and the condition for relaxing each control.

## Completion evidence

The record states which harm was reduced, which paths remain possible, what evidence was preserved or lost, and who owns continuing monitoring. Containment does not mean eradication.

## Tabletop check

Tabletop rapidly growing harm with partial scope, a shared critical server, failed isolation and expired authority. Verify the choice explicitly accounts for delay, service impact and a rollback path.

## Concrete observation contract

The containment decision record should name the exact target set, scope/grant, action
owner, executor, intended risk reduction, expected disruption, operation/job ID, saved
rollback state and acceptance check. Record local client completion and remote service
state separately. A timeout or disconnected client can leave the remote action unknown,
so do not release an occupied resource merely because the local process exited.

Verify the relevant effect through an independent observation: actual access policy,
session state, endpoint isolation state or traffic/resource result within the approved
scope. Keep API acknowledgement, effect verified and residual exposure as separate
statuses. Compare urgent harm reduction with evidence loss and business impact, recording
the decision while investigation continues. Failed and partly applied actions need a
named follow-up; they cannot be summarized as successful containment.
