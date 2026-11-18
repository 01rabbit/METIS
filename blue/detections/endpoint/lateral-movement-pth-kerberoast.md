# Evaluate unusual authentication and service-ticket use

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Do authentication records support unauthorized remote use or suspicious service-ticket collection?

## Evidence to request

Domain-controller ticket events, destination logons, account/SPN inventory, source-device identity, authentication package, logon type and approved management activity.

## Reasoning procedure

- Analyze service-ticket request breadth and rate per requester/source separately from breadth of requesters for one service. State the grouping keys and distinct count.
- An older encryption type can be a compatibility setting; it does not prove ticket cracking. Ticket issuance does not prove offline recovery of a secret.
- For remote authentication, correlate source context, destination session and subsequent privileged activity. A network logon or NTLM event alone does not prove use of a stolen hash.
- Track ticket reuse, explicit credentials and administrative protocols as alternative hypotheses. Avoid deriving a specific mechanism from ambiguous logon metadata.
- Account for NAT, jump hosts, clock offsets and duplicate controller forwarding before attributing a single operator.

## Alternatives and limits

Service migrations, monitoring, backup and central administration produce fan-out and older encryption. Missing destination telemetry leaves successful service access unconfirmed.

## Discriminating checks

Test expected administration, an encryption compatibility exception, duplicate ticket events and an unusual requester with corroborated destination activity. Never validate by collecting or replaying credential material. Credential remediation requires a dependency-aware plan.

## Concrete observation contract

On a domain controller, Security 4769 identifies service-ticket requests with
`ServiceName`, `TargetUserName`, `TicketEncryptionType`, `IpAddress`, `Status` and
available `LogonGuid`. Values such as 0x17 for RC4 and 0x11/0x12 for AES describe
encryption choice, not credential compromise. Legacy service configuration can explain
weaker encryption; a ticket request does not establish that its contents were recovered.

At the destination, Security 4624 `LogonType`, `AuthenticationPackageName`,
`TargetLogonId` and source context describe acceptance. Security 4648 is an explicit
credential attempt, whereas 4625 records failure with status/substatus. Bind the accepted
session to the actual resource operation. Same-account events close in time do not
identify a credential mechanism, and host-local logon IDs cannot be joined across the
fleet without destination context. Use only recorded/inert data for these distinctions.
