# Analyze connection timing in a coverage-aware network hunt

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does a destination relationship show repetitive behavior worth endpoint or application-level investigation?

## Evidence to request

Connection logs, event times, duration, directional bytes, flow state, protocol metadata, sensor location and endpoint attribution if available.

## Reasoning procedure

- Choose grouping keys that represent the intended relationship. Aggregating an entire proxy or NAT address can combine many unrelated clients.
- Deduplicate records and distinguish new connections from active-flow exports. Sort connection starts before computing inter-arrival statistics.
- Compare timing regularity with volume, duration, destination prevalence and asset role. State the observation count and the length of the covered interval.
- Explain the timing statistic used, its denominator and treatment of zero intervals/outliers. A low spread of inter-arrival times is a shape observation, not a probability of maliciousness.
- Account for collection gaps and scheduled network retries. Both can distort interval distributions.
- Use IDS/TLS observations as enrichment, not as a replacement for the time-series analysis. A single packet signature does not measure cadence.

## Alternatives and limits

Monitoring, time services, mobile clients, software updates and persistent sessions can all appear repetitive. Application identity is often unavailable through encryption.

## Discriminating checks

Test a periodic health check, batched collector delivery, one connection exported repeatedly and several clients behind a proxy. Compare the selected event IDs with expected grouping. Endpoint confirmation should precede any strong command-channel attribution.

## Concrete observation contract

In Zeek `conn.log`, preserve connection `uid`, origin/responder tuple, `ts`, `duration`,
byte counts and `conn_state`. Compute intervals only after deduplicating and defining
what constitutes an independent connection. `local_orig`/`local_resp` depend on the
site's configured local networks; `missed_bytes` describes detected stream gaps, and a
zero value does not establish complete sensor coverage.

Attach DNS transaction evidence and `ssl.log` `server_name` only through the relevant
connection/request context. TLS 1.3 may hide certificate details from passive inspection,
and encrypted client hello may remove useful SNI. A later DNS answer or certificate
lookup cannot fill a historical capture gap. Check sanctioned monitoring/update behavior
and destination sharing before attributing a periodic pattern to one host process or
user; endpoint or resolver evidence is needed for that stronger association.
