# Kusto query planning for SOC evidence

## Pick the backend and table

Sentinel Log Analytics and Defender XDR advanced hunting do not expose identical tables or
schemas. Inspect the installed data sources and available columns first. Each table defines its
clock: Defender `Timestamp` records event time, while `SigninLogs.TimeGenerated` records receipt
in Log Analytics; use `CreatedDateTime` for the sign-in occurrence. Check the source contract
before applying one time field across tables.

Typical evidence groups include SecurityEvent/WindowsEvent, SigninLogs, AuditLogs,
OfficeActivity, CommonSecurityLog and AzureActivity in Sentinel, and device process, logon,
network, file and registry tables in Defender. A table name in this guide is not a guarantee
that it is licensed, collected or queryable in the user's tenant.

## Build a bounded query

Choose a time interval and filter before expensive transforms. Project the columns needed to
answer the question. Convert dynamic/typed fields explicitly and distinguish null, empty and
malformed values. String equality and case-insensitive equality have different operators;
token search and substring search are not interchangeable.

For counts, state whether rows, distinct principals, sessions or objects are intended.
Approximate distinct-count functions are unsuitable for an exact answer without an accuracy
assessment. Preserve ordering when describing a sequence; aggregation destroys event detail
unless representative records are retained deliberately.

## Correlation choices

Specify join keys and join kind. The default innerunique behavior can collapse left-side
duplicates, changing a count or sequence population. An inner join can multiply rows when
both sides have repeated keys. Check expected cardinality and inspect unmatched rows.

A join on account alone can connect unrelated sessions. Add host/device, session/process
identity and a bounded temporal relation as appropriate. Principal names can change; use
immutable IDs where available. Watchlists and ASIM parsers require availability/schema checks.

For process lineage, bind device, process ID and creation time or an equivalent stable entity.
For authentication, keep interactive sign-ins separate from token refreshes and service
principals. MFA denial followed by success is a sequence lead, not a standalone verdict.

## Limits and results

Record backend warnings, partial failures, truncation, query time and result size. A portal
display or exported page can show only part of a result. Do not infer the absence of records
from a query that exceeded memory, duration or row limits.

Use a known small population to validate field extraction and cardinality, then expand within
the owner's SIEM lease. Deployment, saved-query changes, export destinations and response
actions require the appropriate authority. See the [integration status](../../../docs/siem-support.md).

## Table and key map

| Backend / table | Concrete columns | Correlation and clock | Validation / result limit |
| --- | --- | --- | --- |
| Defender `DeviceProcessEvents` | `Timestamp`, `DeviceId`, `DeviceName`, `ProcessId`, `ProcessCreationTime`, `ProcessUniqueId`, `InitiatingProcessUniqueId`, `FileName`, `FolderPath`, `ProcessCommandLine`, `AccountSid`, `ReportId` | Join the child's `InitiatingProcessUniqueId` to the parent's `ProcessUniqueId` on the same `DeviceId`; otherwise use PID + creation time | `ReportId` is a repeating counter; keep device and timestamp context. Unique-process fields depend on sensor/platform support. [Process schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-deviceprocessevents-table) |
| Defender `DeviceNetworkEvents` | `Timestamp`, `DeviceId`, `LocalIP`, `LocalPort`, `RemoteIP`, `RemotePort`, `RemoteUrl`, `Protocol`, `ActionType`, `InitiatingProcessId`, `InitiatingProcessCreationTime`, `InitiatingProcessUniqueId` | Relate network initiator to process creation on the same device and lifetime | A local/remote tuple is from the device's perspective. `RemoteUrl` can be absent even with a connection. [Network schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-devicenetworkevents-table) |
| Defender `DeviceFileEvents` / `DeviceRegistryEvents` | `DeviceId`, `Timestamp`, `ActionType`, `InitiatingProcessUniqueId`; file `FolderPath`, `FileName`, `SHA256`; registry `RegistryKey`, `RegistryValueName`, `RegistryValueData` | Reuse the validated process identity; retain native path and operation type | A missing hash or registry value may be uncollected; do not turn it into an empty value. [File schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-devicefileevents-table), [registry schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-deviceregistryevents-table) |
| Sentinel identity and cloud | `SigninLogs`, `AADNonInteractiveUserSignInLogs`, `AADServicePrincipalSignInLogs`, `AADManagedIdentitySignInLogs`, `AuditLogs`, `OfficeActivity` | See [provider-specific columns](../../soc-cloud-identity-forensics/references/entra-m365-okta.md); retain tenant with user/application IDs | Table availability and sign-in populations differ; do not equate Graph property casing with table column casing. [SigninLogs schema](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/signinlogs) |
| Defender email tables | `EmailEvents`, `EmailUrlInfo`, `EmailAttachmentInfo`, `UrlClickEvents`; `NetworkMessageId`, `RecipientEmailAddress` or click `AccountUpn`, `Timestamp` | Join on message ID plus recipient/time as appropriate; preserve URL/attachment multiplicity | Message rows, URLs, recipients, clicks and attachments are distinct units. [Email schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-emailevents-table), [click schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-urlclickevents-table) |
| Sentinel host/firewall ingestion | `SecurityEvent`, `WindowsEvent`, `Syslog`, `CommonSecurityLog`; `TimeGenerated`, `Computer` where defined, event/provider or device fields | Inspect that table's raw payload and normalization before correlating to XDR device IDs | A `Computer` string is not guaranteed to equal `DeviceId`; aliases and connectors require an explicit mapping. [WindowsEvent](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/windowsevent), [CommonSecurityLog](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/commonsecuritylog) |

In Kusto, `==` compares strings with case sensitivity, while `=~` ignores case; `has` is a term
operator and `contains` searches a substring. Declare join kind explicitly: `innerunique` deduplicates
the left input on the join key. Retain the unjoined population when calculating loss or multiplicity.
[Join semantics](https://learn.microsoft.com/en-us/kusto/query/join-innerunique)

`dcount()` estimates distinct cardinality, ignores nulls, and has an accuracy parameter. Record that
parameter and do not present a probabilistic error estimate as a guaranteed maximum.
[Distinct-count contract](https://learn.microsoft.com/kusto/query/dcount-aggfunction)

## Additional table routes

When the relevant connector exists, Defender `CloudAppEvents` supplies cloud-application
actions; `IdentityLogonEvents`, `IdentityDirectoryEvents` and `IdentityQueryEvents` supply
identity authentication, directory changes and directory queries respectively. `DeviceInfo`
and `IdentityInfo` supply enrichment; retain its observation time because an inventory row
may describe a different state from the event being investigated. `AlertEvidence` associates
entities with detections and is not a replacement for the event that caused an alert.
[Defender table catalog](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-schema-tables).

Sentinel `SecurityAlert` uses `SystemAlertId` with `TimeGenerated`; `SecurityIncident` carries
`IncidentName`, `IncidentNumber` and dynamic `AlertIds`. Keep workspace/tenant and update time
with these identifiers, inspect array contents before joining, and separate incident updates
from unique incidents. Alert IDs and incident numbers are different namespaces.
[SecurityAlert](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/securityalert),
[SecurityIncident](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/securityincident).

## Native columns for cloud-application and identity pivots

In the following Defender tables, `Timestamp` is `datetime`, `ReportId` is a `string`
event identifier, and `AdditionalFields` is `dynamic`. Preserve tenant/workspace, table
and source-record coordinates with each identifier. Do not apply the endpoint tables'
repeating-counter interpretation of `ReportId` to these tables or join different tables
on that field without a documented relationship. Inspect dynamic values before expanding
rows, retaining the original event count separately.

| Table | Native columns and types | Join and interpretation boundary |
|---|---|---|
| `CloudAppEvents` | `ApplicationId` and `AppInstanceId`: `int`; `ActionType`, `Application`, `AccountObjectId`, `AccountId`, `IPAddress`, `ObjectId`, `ObjectType`, `ObjectName`: `string`; `ActivityObjects` and `RawEventData`: `dynamic` | Keep application/instance context with object IDs. `AccountObjectId` identifies an Entra account; `AccountId` can use another identity namespace. The integer `ApplicationId` is not an Entra application GUID. Interpret the source JSON with its application contract. [Schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-cloudappevents-table) |
| `IdentityLogonEvents` | `ActionType`, `Application`, `LogonType`, `Protocol`, `FailureReason`, `AccountUpn`, `AccountSid`, `AccountObjectId`, `DeviceName`, `IPAddress`, `DestinationDeviceName`, `DestinationIPAddress`, `TargetDeviceName`: `string`; `Port` and `DestinationPort`: `int` | Preserve source/destination roles. `LogonType` is a string field; validate the table's value vocabulary before equating it to a numeric Windows Security value. Coverage is not identical to all Entra sign-ins. [Schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-identitylogonevents-table) |
| `IdentityDirectoryEvents` | `ActionType`, `Application`, `AccountUpn`, `AccountSid`, `AccountObjectId`, `TargetAccountUpn`, `TargetDeviceName`, `DeviceName`, `IPAddress`, `DestinationDeviceName`, `DestinationIPAddress`, `Protocol`: `string`; `Port` and `DestinationPort`: `int` | Keep acting account separate from target account/device and the service endpoint. Validate each `ActionType` in the deployed schema before interpreting a change. [Schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-identitydirectoryevents-table) |
| `IdentityQueryEvents` | `QueryType`, `QueryTarget`, `Query`, `Protocol`, `AccountUpn`, `AccountSid`, `AccountObjectId`, `TargetAccountUpn`, `DeviceName`, `IPAddress`, `DestinationDeviceName`, `DestinationIPAddress`: `string`; `Port` and `DestinationPort`: `int` | Query target, requester and responding endpoint have different roles. Query text does not establish a successful change or uniquely identify a person. [Schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-identityqueryevents-table) |

Scope account joins to the recorded directory/tenant and time. A UPN or device name can
change; matching display strings are not stable identity proof. Check connector deployment,
action coverage and retention before interpreting an empty table as no activity.

## Additional native endpoint and ingestion selectors

`DeviceProcessEvents.InitiatingProcessFileName` is a `string` describing the initiating
process file, with a process-name fallback when unavailable. It is distinct from the
new process's `FileName` and is not a unique process key. Retain the device and stable
process identity or creation time when relating it to other records.
[Process fields](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-deviceprocessevents-table).
`DeviceNetworkEvents.RemoteIPType` is a `string` address classification, with values
such as `Public`, `Private` and `Loopback`. It is separate from `RemoteIP` and the
operation result; a public address does not establish maliciousness or successful
transfer. [Network fields](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-devicenetworkevents-table).

For an acquired Log Analytics `Event` export, `EventID` is `int`; `Computer`,
`EventLog`, `Source`, `EventData` and `RenderedDescription` are `string`;
`TimeGenerated` is `datetime` for record creation. Preserve table and source-log
identity. This table is not an alias for `WindowsEvent`, and its string payload
must not inherit another table's dynamic schema or a sign-in ingestion clock.
[Event columns](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/event).

`AzureDiagnostics` holds resource logs in Azure Diagnostics mode. Services using
resource-specific mode can send them to separate tables instead. Inspect resource
and category context plus actual columns; fields beyond the table's column limit
can be stored in the dynamic `AdditionalFields` property bag. Preserve property
names and types before expansion. An empty `AzureDiagnostics` result alone does not
establish that the resource emitted no logs.
[AzureDiagnostics storage contract](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/azurediagnostics).
