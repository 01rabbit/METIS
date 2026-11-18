# Prioritize repetitive outbound connections

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is repeated communication unusual for the owning process and asset role, and does content or behavior support command-and-control?

## Evidence to request

Connection start times and outcomes, directional byte counts, destination identity, process mapping, DNS/proxy context and a representative normal interval.

## Reasoning procedure

- Calculate intervals within a single well-defined source/process/destination grouping after deduplicating sensor copies. Sort by event time and report sample count.
- Measure cadence and variation without treating exact regularity as mandatory. Jobs are periodic; covert communication can include jitter, long pauses or persistent connections.
- Report the median inter-arrival time and a stated spread measure, such as the interquartile range divided by a nonzero median. Retain the sample count; tiny samples and interval filtering can manufacture regularity. Choose thresholds from local benign data.
- Compare peer prevalence, destination age in local telemetry and owning process behavior. A rare destination is not automatically malicious.
- Require additional evidence before naming a command channel: attributable requests, endpoint actions or independent intelligence with a known scope. Port 443 does not establish HTTP semantics.

## Alternatives and limits

Health checks, software updates, telemetry and time synchronization can be highly regular. Sensor restarts, flow expiry and collection batching can create artificial cadence.

## Discriminating checks

Test a scheduled updater, duplicate flows, a long-lived connection split by the sensor and an irregular but suspicious sequence. Report observation duration and packet/flow gaps. Blocking a destination requires validation of shared-service impact.

## Concrete observation contract

For Zeek `conn.log`, retain `ts`, `uid`, origin/responder tuple, `duration`, `orig_bytes`
and `resp_bytes`. Deduplicate repeated observations before deriving inter-arrival times;
duration and sensor export cadence are not the interval between independent callbacks.
State the time range, sample count, jitter statistic and data gaps rather than adopting
one universal threshold. Grouping only by a shared destination can merge unrelated hosts.

For endpoint attribution, `DeviceNetworkEvents` can add `DeviceId`, `RemoteIP`,
`RemotePort`, `RemoteUrl` and `InitiatingProcessUniqueId` where supported. Relate that
process to its creation record, accounting for proxies and DNS changes. A periodic TLS
connection can be an updater, monitoring agent or retrying service. Certificate or TLS
validation metadata is supporting context, not proof that a connection is safe or malicious.
