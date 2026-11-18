# Hunt for combinations that threaten recovery and data availability

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Are several preparatory or destructive behaviors appearing together outside an approved operation?

## Evidence to request

Backup administration, recovery configuration, service-control and endpoint events, file-change effects, account privileges and business maintenance calendars.

## Reasoning procedure

- Select a behavioral hypothesis from the environment, such as unexpected interference with recovery followed by broad file changes. A named actor is not required.
- Connect actions using source identity, process lineage and target resources. Do not join unrelated maintenance on a busy host solely because it falls in one window.
- Distinguish a request to change a recovery setting from the verified resulting state. A command line is not its success record.
- Check whether the supposed defensive impairment precedes observed harmful effects or is a responder action afterward.
- Attribute to an actor only with independent supporting intelligence; shared techniques and common tools are insufficient.

## Alternatives and limits

Disaster-recovery drills, storage migrations, backup agents and administrators legitimately modify recovery settings. Scheduled timing does not by itself prove authorization.

## Discriminating checks

Use a maintenance sequence, a failed configuration change, unrelated parallel workflows and an unexpected attributable chain. Record which behavior justified urgency. Move credible ongoing harm to the incident owner without waiting for actor attribution.

## Concrete observation contract

Separate process intent from control outcome. Sysmon 1 or `DeviceProcessEvents` can
locate a process and its creator, but a backup-related command line does not establish
that recovery copies became unavailable. Seek the backup/storage provider's actual
operation ID, target set, result and later availability state, mapping those product
fields explicitly. A failed command and scheduled retention cleanup are different cases.

For file effects, use `DeviceFileEvents` action and initiating process fields with
distinct affected paths/digests. If a signing claim concerns the created process, do not
reuse `InitiatingProcessSignatureStatus`, which describes its parent. Associate the
created file's SHA-1 and device with `DeviceFileCertificateInfo` and preserve trust/time
limitations. These behavioral observations can support scoping without naming an actor
from a tool, note, filename or one technique.
