---
name: soc-incident-report
description: Produce a decision-ready SOC handoff or incident report from reviewed findings, with evidence, uncertainty, response status and assigned follow-up actions.
---

# Reporting and handoff

Read the actual case findings and worker results. Resolve inconsistent time/count models and
unsupported conclusions before drafting. Do not reconstruct evidence from conversational memory.
Use AGENTS.md for privacy, audience and existing authority.

## Choose the deliverable

For Tier 1, lead with disposition, affected scope, why it matters, immediate approved next step
and escalation criteria. Include a small evidence set that another analyst can locate.
For management, explain business effect, actions completed, uncertainty and the requested
decision in plain language. Technical detail belongs in the supporting report.

A full report should cover:
- Case identity, accountable analyst, audience/classification and current response state.
- Confirmed observations separated from hypotheses, with impact denominators and confidence.
- A UTC sequence with original time representations retained in evidence references.
- Typed indicators with context, validity interval, confidence and sharing restrictions.
- Actions actually performed, authorization, actor, timestamp and verified outcome.
- Unresolved questions, collection gaps, alternative explanations and required next evidence.
- Prioritized recommendations tied to findings, responsible owners, effort and acceptance tests.
- Acquisition hashes, query revisions, tool versions and reproducibility notes.

## Avoid consequential overstatement

File access is not automatically exfiltration. A blocked attempt is not completed compromise.
A proposed containment step is not an action already taken. An indicator match is not proof of
actor attribution. Use precise outcome language rather than a confidence adjective alone.

State which facts are directly observed, which are inferred from several records, and which
remain uncertain. A gap that prevents an impact conclusion belongs near that conclusion.
Do not invent an exact volume or chronology when collection is partial.

Map ATT&CK techniques only to evidence-supported behavior and keep conditional mappings
qualified. Defang unsafe destinations in human-readable deliverables. Check the recipient and
data-sharing authority before any external publication; local case reports remain private.

## Close and improve

Confirm unresolved owners and follow-up actions, reconcile usage, and close the runtime case
using the actual CLI help. Document investigation mistakes as well as missing controls.
Turn a recurring gap into a named collection or detection improvement with a verification step.

New durable lessons go through the independent-authoring intake policy. Case narratives,
answer strings, screenshots, source passages and raw evidence do not become shared skills.

Use the [evidence locator contract](../soc-triage/references/evidence-locators.md) for technical attachments. Verify that a second analyst can reopen the cited input and find the named row/record and field; keep sensitive source locations in the private manifest.

For containment, recovery, impact, decision ownership and post-incident improvement, select
the relevant [response decision guide](../../playbooks/README.md). Keep the current case
scope and applicable grants; the guides support decisions and do not authorize external actions.
