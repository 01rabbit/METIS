---
name: soc-siem-hunt
description: Answer defensive scoping and hunting questions from a SIEM using verified data coverage, platform-specific queries, explicit populations and bounded search cost.
---

# Evidence-driven log search

Define the observation that would answer the question, then identify the sensor and dataset
that can contain it. Verify tenant/index, entity scope, retention, required fields and event
time coverage. An unreachable service and a reachable dataset with no matching events are
different outcomes. Consult [connection status](../../docs/siem-support.md) rather than
assuming a working API exists for the selected platform.

Acquire the owner's search resource before dispatch. Estimate cost from interval, index
breadth, group cardinality and expensive joins. Begin with a small representative preview,
then run the required population once the field contract is confirmed. Broad unrestricted
searches are not a prerequisite for every hunt.

## Choose one dialect and its actual backend

- [Splunk SPL](references/splunk-spl.md): indexed versus extracted fields, CIM, acceleration,
  aggregation, search messages and row limits.
- [Elastic and OpenSearch](references/elastic.md): product boundaries, mappings, query modes,
  complete pagination and approximate aggregations.
- [Sentinel and Defender Kusto](references/sentinel-kql.md): table scope and identity joins.
- [Wazuh, Zeek and Suricata](references/wazuh-zeek-suricata.md): decoder and sensor semantics.

Query languages with similar names are not interchangeable. Confirm installed versions,
permissions and a known record before adapting syntax. A normalized field being null can
mean mapping failure even when the raw event has a value.

## Search, correlate and challenge the explanation

Save the query, absolute interval, relevant settings and job/result identity. Explain what
one result means: row, deduplicated event, process, session or asset. Preserve unknown fields
and rejected records. Use robust entity keys rather than display names, reused PIDs or time
alone. Proxy headers and user-agents need corroboration before attributing activity.

IOC matches, rare processes, periodic flows and authentication sequences generate leads.
Compare process context, asset role, approved changes and legitimate automation. A connection
to an address is not evidence that the host executed a file associated with that address.
First observed within a retention interval is not first ever. Give relevant alternative
explanations a query that could actually distinguish them.

## Check whether the result is complete

Inspect query warnings, partial shards, job finalization, row/group caps, pagination and
acceleration coverage. Compare event and ingestion time when late arrival matters. Replay a
known positive record and an appropriate near-miss to expose field or predicate errors.
A zero count supports absence only for the proven sensor/entity/interval and query semantics.
The result must remain incomplete when those conditions cannot be established.

Return the query and coverage receipt, exact or explicitly approximate counts, cited events,
supported finding, alternatives and next evidence request. Detection deployment and SIEM
configuration changes are separate writes controlled by the owner.

## Find the actual schema

The platform references contain concrete field and table maps: [SPL/CIM](references/splunk-spl.md),
[Elastic/ECS](references/elastic.md), [Sentinel and Defender](references/sentinel-kql.md), and
[Wazuh, Zeek and EVE](references/wazuh-zeek-suricata.md). For collector envelopes, container process/flow
observations or session-to-packet pivots, use [observability sources](references/observability-sources.md).
These maps guide inspection of authorized data; their presence does not mean a live API adapter is installed.
