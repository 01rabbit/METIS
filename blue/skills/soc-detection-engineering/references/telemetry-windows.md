# Windows event identities and field joins

Use this reference when a card names Windows process, file, authentication or directory
evidence. These are schema requirements for a candidate, not installed sensors or a
validated query. Preserve raw XML alongside any SIEM projection. Bind the mapping to the
provider, channel, event version and collector version; similarly named columns may have
different meanings. A missing field is unknown, not an empty string to match.

## Endpoint process and artifact records

Microsoft-Windows-Sysmon writes to Microsoft-Windows-Sysmon/Operational. Event 1 gives
`ProcessGuid`, `ParentProcessGuid`, `Image`, `CommandLine`, `User`, `IntegrityLevel` and
`UtcTime` where present in the deployed schema. Join GUIDs on the same endpoint. Event 3
adds connection direction and destination to a process; network collection is disabled by
default. Event 7 supplies image-load evidence and signing metadata but is also disabled
by default. Configuration filters can remove either kind of evidence.

For files, event 11 covers creation or overwrite, not every modification or rename. Its
`TargetFilename` and writer `ProcessGuid` do not prove later execution. Event 15 concerns
alternate data streams. Events 23 and 26 concern deletions; 23 can retain an archived copy
if configured, whereas 26 does not. Confirm actual collection before expecting any record.
Events 12/13/14 concern registry mutation, not reads. For event 13, distinguish
`TargetObject` from `Details`, the written value. The installed Sysmon schema is the
authority for exact field casing, optional fields and supported event versions.

With Microsoft Defender for Endpoint, use `DeviceProcessEvents`: the newly created
process has `ProcessUniqueId`; its creator has `InitiatingProcessUniqueId`. Include
`DeviceId`. Older data may require PID plus process creation time, with an explicit gap if
either is absent. `InitiatingProcessSignatureStatus` describes the creator, not the child.
To assess a file's signature, associate its digest and device with `DeviceFileCertificateInfo`
and retain `IsSigned`, `IsTrusted` and `Signer`. Neither trust nor a publisher name proves
the behavior benign. SHA-256 is often unpopulated in these tables; do not silently compare
it with SHA-1. `ReportId` is a repeating counter, not a global event identifier.

## Security auditing

Microsoft-Windows-Security-Auditing uses the Security channel. Event 4688 records creation:
`NewProcessId`, `NewProcessName`, creator `ProcessId` and version-dependent parent fields.
PID encodings may be hexadecimal. `CommandLine` requires its own audit setting. A PID join
needs host, bounded lifetime and creation time; a logon ID needs host and logon context.

Event 4624 describes an accepted logon on the destination. Examine `LogonType`,
`AuthenticationPackageName`, `TargetLogonId`, `TargetUserName` and available source address.
Type 3 is a network logon, not a mechanism verdict. Event 4625 is a failed logon; retain
`Status` and `SubStatus`. Event 4648 records an explicit-credential attempt, not acceptance.
Event 4769 on a domain controller concerns a service-ticket request: `ServiceName`,
`TicketEncryptionType`, `Status`, `IpAddress`, `LogonGuid` and `TransmittedServices` have
different meanings from the destination's accepted session. Null or all-zero correlation
values cannot serve as identifiers.

For directory mutation, event 5136 requires suitable audit policy and object SACLs.
Use `ObjectGUID` for the changed object, `AttributeLDAPDisplayName` for the attribute and
`OperationType`/`AttributeValue` for the operation. `OpCorrelationID` can relate parts of
one modification. The actor's `SubjectLogonId` is not the object's identity. Before/after
attribute records and current state are separate evidence. Event 4662 concerns audited
directory access; `ObjectType`, `Properties` and `AccessMask` need schema-aware decoding.
Event 4663 concerns audited object use; verify `ObjectType`, `ObjectName`, access rights
and process attribution before calling the operation a read. Registry read visibility does
not come from Sysmon registry-change events.

## Configuration versus use

Security 4697 describes service installation, using `ServiceName`, `ServiceFileName`,
`ServiceStartType` and `ServiceAccount`. Service Control Manager 7045 is a different event
in System; do not map its rendered fields by assuming the Security names. Later service
configuration changes need registry/configuration evidence and do not generate another
4697 merely because the path changed. Security 4698 registers a task using `TaskContent`;
4702 updates one using `TaskContentNew`. These XML fields describe requested principals
and actions, not proof that they ran.

For multi-event fixtures, include PID reuse, another host with the same logon ID, a
directory change with no later authentication, and registration without execution.
Cross-provider raw identifiers and event versions belong in the mapping worksheet before
conversion into a backend query. See [validation integrity](validation-integrity.md).

## Token changes and directory handle requests

Security event 4703 reports changes to privileges in a token. Preserve the two roles:
`SubjectUserSid` and `SubjectLogonId` identify the initiating security context, while
`TargetUserSid` and `TargetLogonId` concern the adjusted token. `ProcessName` and
`ProcessId` identify the process; the PID still needs host and lifetime context.
`EnabledPrivilegeList` names privileges switched on and `DisabledPrivilegeList` names
those switched off. These are lists, not a Boolean elevation verdict. Ordinary management
software can generate this event often. Privilege adjustment does not establish that a
privileged action subsequently occurred.

Resolve collection against the acquired OS/build and effective audit policy. Microsoft's
[dedicated subcategory guidance](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/audit-token-right-adjusted)
lists 4703 under `Audit Token Right Adjusted` success auditing and describes no failure events.
The [Audit CSP mapping](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-audit#detailedtracking_audittokenrightadjusted)
places that policy under `Detailed Tracking`, with device selector
`./Device/Vendor/MSFT/Policy/Config/Audit/DetailedTracking_AuditTokenRightAdjusted`.
Its listed applicability includes Windows 10 1803/1809/1903 with specified servicing updates
and Windows 10 2004 onward; verify the actual edition/build rather than applying it to every OS.
The older [4703 event page](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4703)
labels the subcategory `Audit Authorization Policy Change` and gives Windows 10/Server 2016
as its minimum OS scope. Preserve this documentation discrepancy: confirm the target's
available/effective subcategory, provider/event version and retained collection before
interpreting an absent event. Neither page alone establishes a universal collection prerequisite.

Security event 4661 concerns an attempted handle opening for a directory or SAM object.
Use `ObjectServer` and `ObjectType` to select the correct name/access-right interpretation;
`ObjectName` may identify an account/object rather than a filesystem path. Preserve
`AccessMask`, `AccessList`, `Properties`, the outcome and relevant audit configuration.
`HandleId` can be unavailable or zero and is not a global object ID. Attribute the request
through `SubjectLogonId`, `ProcessId` and `ProcessName` in the same host/session window.
A handle request does not establish reading every attribute or successful enumeration.
See Microsoft's [4661 field contract](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4661).

### Source and target field casing in Sysmon

Microsoft's published Sysmon 13.30 schema 4.81 gives different GUID field spellings for
remote-thread and process-access records. In event 8 version 2, use `SourceProcessGuid`
and `TargetProcessGuid`; event 10 version 3 uses `SourceProcessGUID` and
`TargetProcessGUID`. Both include `SourceProcessId`/`TargetProcessId` and
`SourceImage`/`TargetImage`. Preserve the exact XML `Data` name before the collector's
normalization, and check the deployed schema instead of propagating one spelling to all
events. Event 8 `NewThreadId` is a thread ID, not another process key. Event 10
`SourceThreadId` belongs to the accessing process; `GrantedAccess` is a hexadecimal
32-bit rights mask and `CallTrace` is a string describing captured stack context.
The field names identify observation roles; a handle, thread or stack does not by itself
prove credential collection or the execution of a particular payload.
[Microsoft's versioned event schema](https://github.com/microsoft/MSTIC-Sysmon/blob/main/windows/schemas/sysmonv13.30_4.81.xml).
