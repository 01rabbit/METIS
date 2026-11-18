# Review changes to Kerberos delegation trust

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has a directory change expanded who may act for another identity, and was that new trust subsequently used?

## Evidence to request

Directory modification records with object GUID, attribute, old/new values and actor; applicable object ACLs; KDC service-ticket events; source-host logons; the approved change request.

## Reasoning procedure

- Treat resource-based, account-based constrained, and unconstrained delegation as separate configurations. Preserve the actual security descriptor and resolve trustees at the time of the change.
- For resource-based delegation, inspect changes to msDS-AllowedToActOnBehalfOfOtherIdentity, including deletion and replacement. A directory event without before/after values is an incomplete configuration history.
- Relate the changed resource, requesting account, service principal, source device and subsequent access. Ticket issuance is not proof that the target service accepted an impersonated session.
- Examine newly created machine accounts, permission grants and service-principal changes as possible prerequisites. A single delegation setting cannot establish how control was obtained.
- Review ticket exposure on systems permitting unconstrained delegation separately; missing directory writes do not exclude abuse of existing trust.

## Alternatives and limits

Application onboarding and identity infrastructure maintenance can make identical changes. Directory auditing/SACLs, KDC coverage and service logs must span the relevant controllers and interval. Removing a trust entry does not establish that previously issued credentials are no longer usable.

## Discriminating checks

Use synthetic directory and ticket records for an approved change, an unexpected trustee, missing before-state and unrelated ticket activity. Confirm that only the unexpected, attributable use raises the stronger finding. Plan any trust change or session revocation with its owner.

## Concrete observation contract

Use Security 5136 on domain controllers when the audit policy and object SACL cover the
change. Retain `ObjectGUID`, `ObjectDN`, `AttributeLDAPDisplayName`, `OperationType`,
`AttributeValue`, `OpCorrelationID` and the actor's `SubjectLogonId`. Relevant attributes
include `msDS-AllowedToActOnBehalfOfOtherIdentity`, `msDS-AllowedToDelegateTo` and
`userAccountControl`; interpret their values against directory schema and before/after
state. An attribute-name match is not sufficient to identify the effective trustee.

For subsequent ticket activity, 4769 supplies `ServiceName`, `TicketEncryptionType`,
`Status`, `IpAddress`, `LogonGuid` and raw `TransmittedServices`. A SIEM alias such as a
similarly named transited-services column needs explicit mapping. Ticket issuance and
destination acceptance are different stages: join to the actual service session and
protected operation before claiming effective access. Approved delegation changes are a
necessary benign comparison; 4741 computer creation alone does not show delegation use.
