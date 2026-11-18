# Distinguish network exploration from expected fan-out

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does one source systematically explore services, hosts, names or shares outside its role?

## Evidence to request

Allowed and denied flows, failed handshakes, DNS transactions, share-access auditing, address ownership/NAT history and authorized discovery schedules.

## Reasoning procedure

- Measure vertical breadth (services on a host), horizontal breadth (hosts for a service) and overall host discovery separately. State the interval and distinct keys.
- Preserve failed attempts. Logs retaining only established connections can miss much of the behavior under investigation.
- For name queries, distinguish transfers, reverse lookups, ordinary retries and broad name exploration. Resolver attribution differs from original-client attribution.
- For shares, separate successful access, permission checks and enumeration. Event rows are not unique shares or files.
- Compare rate and breadth with the source role and scanner authorization; slow exploration may need longer bounded windows.

## Alternatives and limits

Asset management, service discovery, backup, monitoring and failed deployments can create fan-out. A shared NAT or proxy can aggregate many benign clients.

## Discriminating checks

Test approved scans, a busy proxy, denied-only probes, duplicate flows and a low-rate exploration sequence. Confirm that destination normalization does not merge IPv4/IPv6 identities incorrectly. Validate from records; do not probe third-party systems.

## Concrete observation contract

From Zeek `conn.log`, aggregate distinct destination addresses and ports per observed
origin over a stated interval, retaining `conn_state`, duration and tuple evidence.
Separate unsuccessful connection attempts from established sessions; retransmissions and
repeated sensor observations must not inflate target counts. Resolver traffic may need
`dns.log` query and response-code context rather than direct endpoint attribution.

For Windows share inspection, Security 5140 describes share access while 5145 records a
detailed share access check. In 5145 retain `ShareName`, `RelativeTargetName`, `IpAddress`,
`AccessMask` and `SubjectLogonId`. A checked path does not itself show that file contents
were read. Tie the logon ID to the destination's session, then verify an actual operation
where required. Authorized inventory/scanning ranges and maintenance windows are relevant
alternatives; a high destination count alone does not identify an intruder.
