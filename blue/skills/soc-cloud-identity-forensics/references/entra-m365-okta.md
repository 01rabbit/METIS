# Identity-provider and collaboration audit

## Microsoft identity

Separate interactive sign-ins, noninteractive token activity, service principals and managed
identities. They represent different populations and may be stored in different tables.
Relate principal, tenant, application/resource, IP, device, session and correlation identifiers.

Inspect ResultType and authentication details in context. A success does not prove MFA was
performed at that moment; a token may reuse an existing authentication claim. A denial or
timeout is not uniquely a malicious MFA attempt. Test a sequence of repeated prompts and
subsequent success while preserving principal/source keys and the ordering window.

Treat password spraying, travel anomalies and unfamiliar devices as hypotheses. VPN egress,
mobile networks, shared infrastructure and device inventory gaps create alternatives.
Conditional Access outcome and authentication requirement are distinct from user intent.

For audit changes, examine actor and target of role assignments, privileged activation,
credential/method registration, application consent, service-principal changes and federation
configuration. Expand nested modified properties carefully and preserve old/new values.

## Microsoft 365

Use the workload-specific operation and outcome. Mail access, mailbox search, item access,
send actions, forwarding/inbox rules, delegation and file sharing are separate behaviors.
An aggregated audit record may refer to multiple items; event count is not necessarily item
count. Licensing, audit settings, retention and record aggregation affect coverage.

Relate stable account/session/message/file coordinates rather than proximity in time alone.
An email delivery record cannot prove the message was opened. An authorized app's mailbox
access may be legitimate; identify consent, permissions and expected workload.

## Okta

Inspect event type, actor, target, client, outcome and transaction/session linkage. Different
events can describe stages of one authentication attempt. Distinguish authentication,
MFA challenge, session issuance, application SSO and configuration changes.

Investigate factor resets/enrollments, policy changes, application assignments and privileged
account changes against administrator activity. Missing or changed schema fields must not
silently become benign outcomes.

## Cross-provider findings

Keep tenant IDs and immutable user IDs alongside mutable names. Correlate issuance, sign-in,
audit change and downstream workload access while accounting for time skew and retention.
A shared IP is weak linkage; token/session and provider correlation fields can strengthen it.
Report exactly which access or change is observed and what credential/session control action
is recommended. Actual revocation or account changes need scoped authority.

## Provider-specific schema coordinates

API property names and SIEM column names are separate schemas. Confirm the actual export before
choosing a selector; preserve tenant and original event IDs in every derived table.

| Evidence source / location | Fields to preserve | Correlation and time | Validation / conclusion limit |
| --- | --- | --- | --- |
| Microsoft Graph `/auditLogs/signIns` | `id`, `createdDateTime`, `userId`, `userPrincipalName`, `ipAddress`, `appId`, `appDisplayName`, `clientAppUsed`, `status.errorCode`, `status.failureReason` | Event time is UTC; use tenant + user ID + app/session context, and retain `correlationId` | `status.errorCode=0` describes sign-in success; pagination and permissions affect available rows. Display names are mutable. [Graph signIn](https://learn.microsoft.com/en-us/graph/api/resources/signin) |
| Sentinel `SigninLogs` | `TimeGenerated`, `CreatedDateTime`, `Id`, `UserId`, `UserPrincipalName`, `IPAddress`, `AppId`, `ResultType`, `ResultDescription`, `IsInteractive` | Use `CreatedDateTime` for sign-in occurrence time; `TimeGenerated` records receipt/publication in Log Analytics. `ResultType` is string-valued and `"0"` indicates success | Keep `AADNonInteractiveUserSignInLogs`, `AADServicePrincipalSignInLogs` and `AADManagedIdentitySignInLogs` populations separate. [SigninLogs columns](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/signinlogs) |
| Sign-in authentication context | Graph v1.0 `conditionalAccessStatus`, `deviceDetail`, `riskDetail`; inspect the version-specific authentication and Sentinel column contracts below | Relate individual authentication steps and session context to the same sign-in | An unobserved/hidden risk value is not low risk. A denial followed by success is a lead requiring user/session corroboration, not automatic proof of hostile MFA approval. [Graph signIn](https://learn.microsoft.com/en-us/graph/api/resources/signin) |
| Graph `/auditLogs/directoryAudits` | `activityDateTime`, `activityDisplayName`, `initiatedBy.user` or `.app`, `targetResources[]`, `result`, `correlationId` | In `modifiedProperties[]`, select `displayName` before comparing `oldValue` and `newValue`; preserve target resource ID | Array position is not a stable property identifier. App ID, service-principal object ID and user ID are different namespaces. [directoryAudit](https://learn.microsoft.com/en-us/graph/api/resources/directoryaudit) |
| Sentinel `AuditLogs` | `ActivityDateTime`, `OperationName`, `InitiatedBy`, `TargetResources`, `Result`, `CorrelationId`, `Id` | Expand targets with their IDs and property names, preserving parent event ID | Expanding multiple changed properties multiplies rows; count parent operations separately. [AuditLogs columns](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/auditlogs) |
| Microsoft 365 audit export / API content | `Id`, `CreationTime`, `Operation`, `RecordType`, `Workload`, `OrganizationId`, `UserId`, `ClientIP`, `ResultStatus` | CSV `AuditData` can hold a serialized JSON record; parse that layer before selecting nested properties | Use workload-specific result semantics. Audit-record counts, recipients and accessed items are not interchangeable. [Activity schema](https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-schema) |
| Mail access and configuration audit | `MailItemsAccessed`, `New-InboxRule`, `Set-InboxRule`, `Set-Mailbox`; operation-specific `Parameters[]`, `Folders[]`, `OperationProperties[]` | Record parameter name/value pairs and mailbox/item identifiers where present; separate rule changes, bind access and sync access | Aggregation, license, throttling and retention determine observation granularity. A rule creation or access record does not prove recipient reading. [Mail-access interpretation](https://learn.microsoft.com/en-us/purview/audit-log-investigate-accounts) |
| Okta `/api/v1/logs` | `uuid`, `published`, `eventType`, `actor.id`, `actor.alternateId`, `target[]`, `client.ipAddress`, `outcome.result`, `outcome.reason` | `published` is the event clock; use `uuid` for event identity, `transaction.id` for transaction and `authenticationContext.externalSessionId` for session context | Those keys have different cardinalities, and session IDs can be null. Follow pagination until the bounded interval is complete. [System Log semantics](https://developer.okta.com/docs/reference/system-log-query/) |
| Okta authentication and changes | `user.session.start`, `user.authentication.auth_via_mfa`, `system.push.send_factor_verify_push`; `debugContext.debugData`, `client.userAgent`, `securityContext` | Join related user/app/transaction observations with an explicit time bound | Event availability and meanings vary by engine/features; interpret event names through the catalog, not keyword matching. [Event catalog](https://developer.okta.com/docs/reference/api/event-types/) |

For an unfamiliar sign-in error, preserve its numeric/string value and look it up in the
[Entra error reference](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes).
For example, `50126` concerns invalid credentials and `53003` concerns Conditional Access blocking;
neither code alone identifies an attacker. Do not count different authentication stages as different
people, and do not infer a precise actor from a shared NAT address.

Clock distinction: [sign-in ingestion timestamps](https://learn.microsoft.com/en-us/entra/identity/monitoring-health/concept-interactive-sign-ins#timegenerated-field).

## Authentication details, risk and location have separate schemas

For Graph v1.0 sign-ins, `location` is a `signInLocation` object, and
`riskLevelDuringSignIn` is the `riskLevel` enum represented by a JSON string. Keep it
separate from `riskLevelAggregated`; `hidden` reflects unavailable protection/detail,
not an assessment of low risk. [Graph v1.0 fields](https://learn.microsoft.com/en-us/graph/api/resources/signin?view=graph-rest-1.0).

The Graph **beta** contract lists `authenticationDetails` as a collection of
`authenticationDetail`, `authenticationRequirement` as String and the deprecated
`mfaDetail` as an object of that name. Do not silently require these beta fields in
a v1.0 export. The requirement describes the stage reached and does not account for
previously satisfied claims; it is not proof of a new MFA interaction. Preserve API
version and the original object/array structure. [Graph beta fields](https://learn.microsoft.com/en-us/graph/api/resources/signin?view=graph-rest-beta).

| Sentinel table.column | Documented Kusto type and reading boundary |
| --- | --- |
| `SigninLogs.ConditionalAccessStatus` | `string`; the recorded Conditional Access result is `success`, `failure` or `notApplied`. Keep it distinct from the overall sign-in result; a policy outcome alone does not establish user intent |
| `SigninLogs.DeviceDetail` | `dynamic`; device context can contain `deviceId`, OS and browser information. Inspect the acquired object before selecting members; this context alone does not authenticate a person or prove endpoint control |
| `SigninLogs.AuthenticationRequirement` | `string`; retain the recorded requirement separately from authentication outcomes |
| `SigninLogs.AuthenticationDetails` | `string`; inspect and parse its serialized content before treating it as an array or expanding steps |
| `SigninLogs.MfaDetail` | `dynamic`, deprecated; missing content is not proof that MFA was absent |
| `SigninLogs.RiskLevelDuringSignIn` | `string`; preserve `hidden`, unknown and missing values separately |
| `SigninLogs.Location`, `SigninLogs.LocationDetails` | `string` country code and `dynamic` detailed location respectively; neither is a verified physical position of a person |

These types come from the [SigninLogs table contract](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/signinlogs).
Check the acquired connector schema before translating properties between sources;
capitalization alone is not a conversion. Keep the parent sign-in ID with expanded
steps and do not turn their row count into a count of people or sessions.

## Okta network enrichment selectors

Within a System Log event, preserve `securityContext.asNumber` and
`securityContext.isProxy` as distinct enrichment values. The official Java SDK 19.0.0
model exposes nullable Integer and Boolean values respectively: an absent value is
neither zero nor false. The former is an autonomous-system number; the latter reports
a known-proxy classification. Neither authenticates an actor or establishes malicious
intent. Keep them with the original `uuid`, client IP and event time; an ASN is not a
stable user/session join key. [Versioned security-context model](https://developer.okta.com/okta-sdk-java/19.0.0/apidocs/com/okta/sdk/resource/model/LogSecurityContext.html).

## Selected collaboration audit operation names

The following names are for acquired Microsoft 365 audit records, using publisher
references checked on 2026-09-30. Match the `Operation` string together with
`Workload`, `RecordType`, tenant and outcome; they are not Graph sign-in property names.

| `Operation` | Recorded activity and limit |
| --- | --- |
| `UpdateInboxRules` | Outlook client rule creation, modification or removal; distinguish it from `New-InboxRule` and `Set-InboxRule` |
| `Add-MailboxPermission` | The mailbox activity catalog describes FullAccess delegation; service maintenance can also produce this event |
| `FileDownloaded`, `FileAccessed` | Download and access respectively; access can involve a system account, and repeated access by the same user to the same file is suppressed for five minutes |
| `FileSyncDownloadedFull` | OneDrive.exe sync download; the older `FileSyncDownloadedPartial` belongs to retired Groove.exe behavior and is deprecated |
| `AnonymousLinkCreated`, `SharingInvitationCreated`, `AddedToSecureLink` | Anonymous-link creation, sharing invitation and authorization of another entity on a secure link respectively; none establishes that the recipient used the link |

These distinctions follow the [activity catalog](https://learn.microsoft.com/en-us/purview/audit-log-activities).
Audit settings, licenses and retention bound visibility. File-event counts are not
necessarily item or deliberate human-read counts. Catalog presence does not guarantee
that an event is emitted in every tenant.

For Exchange administration, `New-TransportRule` identifies transport-rule creation
in the [rule audit reference](https://learn.microsoft.com/en-us/purview/audit-log-search-mailbox-rules).
`Add-RecipientPermission` is the cloud-service cmdlet for `SendAs` rights, distinct
from FullAccess; retain it as an admin-audit operation selector when present in the
export. [Permission meaning](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/add-recipientpermission?view=exchange-ps).
Exchange admin auditing uses cmdlet names but has exceptions; an absent record is not
proof that no change occurred. A permission-change record does not establish use.

For `Set-Mailbox`, preserve the parameter name `ForwardingSmtpAddress` within the
acquired `Parameters[]` name/value collection; it is not a separate `Operation`.
The cmdlet parameter type is `ProxyAddress`, not an asserted JSON storage type.
`ForwardingAddress` takes precedence when both are set, and `DeliverToMailboxAndForward`
affects delivery behavior. A setting alone does not prove any message was forwarded.
[Parameter contract](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/set-mailbox?view=exchange-ps#-forwardingsmtpaddress).

Documentation headings `SearchQueryInitiatedExchange` and
`SearchQueryInitiatedSharePoint` identify search-auditing features. The catalog's
`Operation` values are `SearchQueryInitiated` and `SharepointSearchQueryInitiated`
respectively. Preserve actual exported spelling; do not substitute a heading as a
raw selector. Exchange search logging requires explicit enablement, while the checked
[setup reference](https://learn.microsoft.com/en-us/purview/audit-get-started#step-3-enabledisable-searchqueryinitiatedexchangesearchqueryinitiatedsharepoint-events)
says SharePoint search logging is enabled by default. Confirm the acquired tenant's
configuration and licensing for the relevant time period.

`UserLoggedIn` is documented for Entra STS audit records (`RecordType=15`), and
`UserLoginFailed` is named in the STS schema. These are not proof of downstream
resource access. In this workload, `ResultStatus=Succeeded` may describe HTTP success
without successful authentication. Preserve optional string `ErrorCode` and
`LogonError`; the schema defines error code `0` as successful login. Keep request and
session context before correlating with sign-in or workload records.
[STS activity](https://learn.microsoft.com/en-us/purview/audit-troubleshooting-scenarios),
[workload result and error fields](https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-schema).

## Selected Okta change-event identifiers

These are `eventType` string values from the [publisher catalog](https://developer.okta.com/docs/reference/api/event-types/)
checked on 2026-09-30. The Since column is the catalog's introduction marker, not
proof of event coverage in an acquired organization.

| `eventType` | Since | Meaning to retain |
| --- | --- | --- |
| `user.mfa.factor.deactivate`, `user.mfa.factor.reset_all` | 2016.11 | Reset one factor versus all factors; in Identity Engine these concern authentication-method or all-authenticator unenrollment respectively |
| `user.mfa.factor.update` | 2016.11 | Factor update |
| `user.account.reset_password`, `user.account.unlock` | 2016.15 | Password reset versus automatic account unlock; the latter is not a generic administrator-unlock event |
| `application.user_membership.add`, `group.user_membership.add` | 2016.02 | Application assignment versus group membership; determine the target's actual privileges separately |
| `system.api_token.create` | 2016.12 | Creation of an unscoped API token; does not prove subsequent token use |
| `user.session.impersonation.initiate` | 2016.09 | Impersonation-session initiation; retain outcome and later session evidence |
| `policy.lifecycle.update`, `policy.rule.deactivate` | 2016.14 | Policy update versus rule deactivation |

No retirement marker was shown for these selected entries in the checked catalog.
Engine, enabled features and collection coverage still apply. Preserve `uuid`,
`published`, `actor`, `target[]` and `outcome` with each event; reset, membership and
policy-change names alone do not establish malicious intent or successful access.
