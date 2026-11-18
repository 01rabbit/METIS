# Review durable changes to directory control

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has an identity gained continuing control through replication rights, authentication material or directory configuration?

## Evidence to request

Directory permissions and changes, replication activity with source identity, privileged group history, authentication logs, policy changes and backup/identity-sync inventories.

## Reasoning procedure

- Separate replication access, authentication forgery hypotheses and durable configuration changes. A replication operation concerns credential access; persistence requires evidence of retained control.
- For replication requests, verify the effective replication rights and whether the source is an approved controller or synchronization service. Record object and scope where telemetry allows.
- Correlate unusual ticket use with key ownership, service context and directory history. Ticket anomalies alone do not distinguish a forged credential from logging gaps or time errors.
- Review rights granted to durable principals and changes to authentication infrastructure. Account deletion alone may not remove other control paths.
- Keep remediation scope tied to demonstrated trust exposure; domain-wide actions require a planned recovery sequence.

## Alternatives and limits

Backup, migration and hybrid identity systems can possess sensitive directory rights. Missing events on one controller cannot exclude activity on another. Some persistence hypotheses require host or memory evidence beyond directory logs.

## Discriminating checks

Test approved replication, an unexpected source with new permissions and incomplete controller coverage. Findings must distinguish rights, use and retained control. Do not validate by extracting credentials or manufacturing authentication artifacts.

## Concrete observation contract

For directory-state changes, Security 5136 can identify `ObjectGUID`,
`AttributeLDAPDisplayName`, `OperationType`, `AttributeValue` and `OpCorrelationID`.
Changes involving `nTSecurityDescriptor` require an actual before/after descriptor and
schema-aware trustee/right interpretation; the attribute name alone does not identify
who gained effective access. Collection needs appropriate policy and object SACLs.

Security 4662 can expose audited use of directory rights through `Properties`,
`ObjectType`, `AccessMask` and `SubjectLogonId`. Resolve replication-related rights with
the directory schema and distinguish a configured grant from its observed use. Neither
alone proves credential collection or durable persistence. Correlate the actor/session,
affected object and later accepted access, with legitimate directory replication and
administrative recovery as alternatives. Missing SACL coverage must not become a negative
finding about the activity itself.
