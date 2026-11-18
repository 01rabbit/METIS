# Incident-response decision guides

The 12 guides below describe decisions, evidence and responsibilities. They support a responder; they do not authorize external actions or claim that an organization has exercised the procedure.

## Response contract

- Keep one accountable owner for incident coordination and an explicit decision owner for each consequential action. The AI owner coordinates workers and presents results; human business, legal and service authority remains with the applicable owners.
- Investigation, containment, communication and impact assessment can proceed together. Credible ongoing harm can justify proportionate authorized containment before complete scoping or attribution.
- Apply existing user authorization and scoped owner grants. New external writes, containment changes or messages outside that scope require the owner to resolve authority. Do not ask repeatedly for a grant that already covers the action.
- Compare the consequences of acting, waiting and doing nothing. Preserve evidence when feasible, but physical safety and urgent harm reduction can outweigh collection completeness. Record the tradeoff and lost visibility.
- Keep original evidence, private case notes, identities, secrets and worker logs outside Git. A hash verifies acquired-byte equality, not acquisition completeness or truth of origin.
- Distinguish technical execution from verified effect. An API success response, restored service or closed ticket is only one part of the relevant acceptance test.
- Record assumptions and gaps while they are fresh. Revising scope and conclusions is expected when new evidence arrives.

Each action record should identify the case, decision, resources, evidence references, authority, executor, time, observed outcome, rollback and unresolved risk. Use the [owner contract](../AGENTS.md) and [incident-report skill](../skills/soc-incident-report/SKILL.md) for task-specific operation and reporting.

## Readiness and exercises

Before operational use, assign actual roles, service dependencies, contact paths, query/VM/session limits and authority boundaries. Walk the guide with a tabletop that includes missing telemetry, unavailable owners and failed actions. Retain what participants actually did and which decisions remain untested. A reviewed document is not a completed exercise.

[NIST SP 800-61 Revision 3](https://csrc.nist.gov/pubs/sp/800/61/r3/final) integrates incident response with cybersecurity risk management and supersedes Revision 2. The guides here are METIS decision aids, not a reproduction of that publication or a statement of formal conformance. If an organization retains an older phase vocabulary, explicitly map its real decision responsibilities rather than assuming a change of labels leaves all requirements unchanged.

## Select a guide

- [Maintain a case that another analyst can continue](incident-response/case-management.md)
- [Evaluate indicators as scoped evidence](incident-response/common-attack-iocs.md)
- [Communicate incident decisions through an authorized channel](incident-response/comms-plan.md)
- [Choose containment while uncertainty remains](incident-response/containment.md)
- [Turn an alert into a defensible incident decision](incident-response/detection-identification.md)
- [Preserve evidence without obscuring acquisition limits](incident-response/dfir-evidence.md)
- [Remove established control paths and restore service with evidence](incident-response/eradication-recovery.md)
- [Quantify impact without merging facts and estimates](incident-response/impact-assessment.md)
- [Classify an incident without mistaking labels for evidence](incident-response/incident-taxonomy.md)
- [Assign decision ownership across the response program](incident-response/ir-frameworks-roles.md)
- [Coordinate investigation, protection and recovery as overlapping work](incident-response/ir-lifecycle.md)
- [Turn an incident into tested improvements](incident-response/postmortem-rca.md)

## Concrete observation contract

At a minimum, a private response record needs case/decision IDs, UTC event and recording
times, asset/account scope, evidence locators, the responsible decision owner, executor,
applicable grant, planned action, observed result and unresolved risk. Define these as
local case fields; they are not a universal incident-management product schema.

For METIS case material, [case management](incident-response/case-management.md) identifies
the `.metis-state/journal/{case}/` record files. [Evidence preservation](incident-response/dfir-evidence.md)
identifies common acquisition locations and consistency constraints.
[Detection decisions](incident-response/detection-identification.md) separate the raw
event from the normalized alert. Use those records to justify containment and recovery
acceptance, preserving collection failure and unknown outcomes explicitly. Historical
document or model review does not substitute for an organization-specific tabletop.
