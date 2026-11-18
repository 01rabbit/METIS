# Assess unexpected transit through an intermediate host

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a host forwarding traffic between security zones outside its assigned role?

## Evidence to request

Flow timing/direction and endpoints on both sides, listener/process ownership, forwarding configuration, routing/NAT design and approved remote-support sessions.

## Reasoning procedure

- Compare inbound and outbound relationships with overlap, byte patterns and process ownership. Similar byte counts alone do not prove that two flows carry the same content.
- Inspect explicit forwarding configuration as capability evidence, then look for actual listener and flow activity. Configuration presence is not proof of use.
- Use command metadata only as a lead; utilities can be renamed and ordinary SSH sessions can be legitimate. Do not rely on one tool-name list.
- Distinguish application proxies, reverse tunnels, ordinary routing and direct connections. The observed intermediate host is not automatically the original operator.
- Document asymmetric visibility, NAT and multiplexing before asserting the route.

## Alternatives and limits

Bastions, development tunnels, support tools, load balancers and disaster-recovery paths can legitimately bridge segments. Flow exporters may sample away one leg.

## Discriminating checks

Test approved proxy traffic, unrelated simultaneous flows, inactive forwarding configuration and a process-attributed transit pair. Do not establish a tunnel to make a rule fire. Closing a remote-support path requires an owner-approved impact decision.

## Concrete observation contract

For Windows forwarding configuration, preserve the relevant
`HKLM\SYSTEM\CurrentControlSet\Services\PortProxy` state and its listen/connect address
and port mapping. The Windows portproxy facility supports TCP; do not describe it as a
generic UDP forwarder. Sysmon 12/13 can show configured registry mutations if collected,
but their presence proves neither a bound listener nor traffic through the mapping.

Relate a listening socket and its owning process to both observed connection legs.
With Zeek, keep the two `uid` values, endpoint tuples, times and byte directions separately;
there is no guaranteed shared UID across the forwarder. Incomplete visibility of one leg
limits the conclusion. An approved remote-support tunnel should be checked against its
owner, target, time window and observed use, not excused solely by the program name.
