---
name: soc-triage
description: Frame a new SOC alert or suspected incident, assess immediate impact and evidence coverage, and select the needed forensic or hunting specialist.
---

# Investigation intake

Turn the request into a decision: affected entity, suspected activity, relevant period,
needed confidence and deadline. Record scope, authority and resource limits with the owner.
Reuse the owner's case. A fully supplied, tools-prohibited question uses the evidence-only
exception in AGENTS.md; case setup must not override the requested response format.

## Decide what evidence can settle the question

Keep a plausible legitimate explanation alongside the suspected incident. For each, identify
an observation that would distinguish it from the other. A claim about a consequence needs
a causal connection; chronological proximity alone does not show what produced that effect.

Choose collection by loss risk and operational impact. Connections, running processes and
memory can change rapidly, but acquisition itself consumes resources and alters the host.
Remote logs can often be checked in parallel; their retention and query cost still matter.
A memory capture or production change needs the authority described in the owner contract.
Do not enforce a universal acquisition order when safety or availability requires another.

## Select the evidence path

| Evidence or immediate need | Skill |
| --- | --- |
| Searchable central logs or estate-wide scope | [soc-siem-hunt](../soc-siem-hunt/SKILL.md) |
| Running host requiring authorized collection | [soc-remote-triage](../soc-remote-triage/SKILL.md) |
| Disk artifacts, event files, registry or RAM image | [soc-host-forensics](../soc-host-forensics/SKILL.md) |
| Packet capture, flow or sensor records | [soc-network-forensics](../soc-network-forensics/SKILL.md) |
| Cloud service or identity-provider audit | [soc-cloud-identity-forensics](../soc-cloud-identity-forensics/SKILL.md) |
| Mail message or mailbox | [soc-email-forensics](../soc-email-forensics/SKILL.md) |
| Offline browser databases | [soc-browser-artifacts](../soc-browser-artifacts/SKILL.md) |
| Suspicious program, document or package | [soc-malware-triage](../soc-malware-triage/SKILL.md) |
| Console interaction or reputation lookup | [soc-browser-console](../soc-browser-console/SKILL.md) |
| Reachability, credentials or session constraints | [soc-lab-access](../soc-lab-access/SKILL.md) |
| Proposed detection or noisy alert | [soc-detection-engineering](../soc-detection-engineering/SKILL.md) |
| Decision record and handover | [soc-incident-report](../soc-incident-report/SKILL.md) |

Read [artifact integrity](references/artifact-integrity.md) when dealing with containers,
exact numbers, hostile repositories, format-sensitive questions or partial extraction.
Confirm tools can read the supplied format before promising a result.
For supplied JSON, the [artifact reader](../../docs/artifact-tools.md) rejects duplicate keys
and nonfinite numbers, and can compare one numeric field exactly while retaining ties.

## Return a decision with its limits

Provide the observed facts, supported interpretation, competing explanation, affected scope
and missing evidence. Each consequential fact needs an artifact location and original time;
retain UTC conversion, clock uncertainty and precision where relevant. Distinguish source
values from derived values. Explain whether counts describe rows, events, sessions or people.
A user-agent, hostname or forwarded address is a claim by its emitter, not verified identity.

Recommend urgent protective action when justified, with business effects, reversibility and
lost evidence stated. Record what actually happened separately from recommendations. Killing
processes, isolating hosts and revoking sessions can change forensic state; key rotation alone
does not necessarily terminate every issued session. Use scoped authority for any action.
Conclude as supported, benign-explained or inconclusive within the measured coverage; do not
extend a narrow negative into a clean bill of health for the estate.

Before dispatching, use [evidence locators](references/evidence-locators.md) to specify where a value can be re-read. For archive entries, Git objects, JSON/RPC fields and bundled numeric-result coordinates read [container and structured fields](references/container-and-structured-fields.md).
