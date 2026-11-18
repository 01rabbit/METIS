---
name: soc-network-forensics
description: Interpret existing packet captures, flow records and network-sensor logs to reconstruct communications, validate transfer evidence and assess suspicious patterns.
---

# Recorded network investigation

Establish what the sensor could observe: interfaces, capture point, time source, packet loss,
snapshot length, filters and encryption. Choose an installed parser for the actual capture
format and preserve its diagnostics. This skill does not authorize active probing or provide
a parser for every industrial, radio or message-based protocol.

Read the [network handbook](references/analyst-handbook.md) for stream reconstruction,
DNS populations, application outcomes, industrial traffic or recorded signal interpretation.
Use [host evidence](../soc-host-forensics/SKILL.md) when attributing traffic to a process.

Deliver conversations or extracted objects with sensor/artifact coordinates, entity roles,
direction, time, completeness and confidence. Explain any deduplication across sensors and
any inferred NAT mapping. Separate a connection attempt, protocol acknowledgement and
confirmed application effect. Report pattern-based leads together with plausible normal
traffic and the additional evidence needed to decide between them.

Use the [packet and service-log field map](references/packet-format-map.md) for exact capture headers,
HTTP/DNS selectors, host-name observations, printer streams and archived space-link records.
For file/flow/certificate joins use [Zeek and EVE fields](../soc-siem-hunt/references/wazuh-zeek-suricata.md);
for session-index and container telemetry use [observability sources](../soc-siem-hunt/references/observability-sources.md).
