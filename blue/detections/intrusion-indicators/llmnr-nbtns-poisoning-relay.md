# Investigate unexpected local name resolution and authentication paths

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has a host answered name-resolution requests outside its authorized role, and did clients subsequently authenticate to an unexpected endpoint?

## Evidence to request

Local name-resolution packets or parsed records, address/hostname inventory, switch/client context, authentication events and service security configuration.

## Reasoning procedure

- Identify which host responded to which question and whether it was expected to own that name. A response count alone cannot distinguish the legitimate responder.
- Correlate resolution, connection and authentication using client identity and time while accounting for caching and retries.
- Treat authentication forwarding as a separate hypothesis that needs evidence from the receiving service; name-resolution anomalies alone do not prove a relayed session.
- Review IPv6 address/DNS provisioning as a parallel trust path, with authorized infrastructure inventory rather than assuming every new responder is hostile.
- Assess protocol-specific controls such as name-resolution policy, signing and channel protections against the deployed service configuration.

## Alternatives and limits

Printers, legacy services, multihomed devices and infrastructure changes can generate unexpected responses. Encrypted or partial captures can omit the relevant authentication exchange.

## Discriminating checks

Test a normal local responder, stale inventory, duplicate answers and a correlated unexpected service session. No spoofed responses or credential forwarding are needed for validation. Infrastructure changes require a coordinated compatibility review.

## Concrete observation contract

Separate UDP name-resolution families in the retained traffic: LLMNR usually uses port
5355, NBNS 137 and mDNS 5353. A response should be related to the requesting host,
question, transaction context and responding address, with retransmissions distinguished.
Ports and an unexpected responder alone do not establish credential use or a relay.

On the service that accepted authentication, inspect Security 4624 from
Microsoft-Windows-Security-Auditing. `LogonType`, `AuthenticationPackageName`, `IpAddress`,
`WorkstationName`, `TargetUserName` and `TargetLogonId` help bind the accepted session.
Type 3 is network authentication, not proof of how credentials arrived. Correlate that
session with the actual protected-resource operation and resolution observations; record
clock offsets and proxy hops. A legitimate resolver change and a failed authentication
after an unusual answer must remain distinct cases.
