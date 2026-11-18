# Evaluate destructive file activity with corroborating context

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a process causing unauthorized widespread data unavailability, and how quickly must the response reduce harm?

## Evidence to request

Per-process file modifications, renames and errors; affected directories and owners; backup/recovery changes; security status; user reports and business-service availability.

## Reasoning procedure

- Group file effects by attributable process/host and bounded time, preserving both attempted and completed operations. File-event counts are not automatically unique affected files.
- Combine abnormal rewrite/rename breadth with content or accessibility evidence and relevant recovery-control changes. Extensions or ransom-like text alone do not establish encryption.
- Check whether network-share activity is attributed to the client process or only to a server-side service. Do not combine all clients into one actor.
- Prioritize credible ongoing harm even while scoping remains incomplete; preserve the uncertainty in the incident record.
- Assess backup integrity and possible data exposure separately. Encryption evidence neither proves nor excludes prior exfiltration.

## Alternatives and limits

Backup, synchronization, bulk conversion, migration and legitimate encryption can produce high file churn. Sensor sampling can underestimate affected data.

## Discriminating checks

Use synthetic bulk-backup, rename-only, failed-write and attributable destructive-effect records. Never encrypt test data to validate a rule. The owner selects containment using current authority, service impact and the cost of waiting.

## Concrete observation contract

Use an actual file-operation source. In `DeviceFileEvents`, retain `ActionType`,
`FolderPath`, `FileName`, and `InitiatingProcessUniqueId` with `DeviceId`.
`DeviceFileEvents.PreviousFolderPath` and `DeviceFileEvents.PreviousFileName` are `string`
columns: the former identifies the folder before the recorded action, and the latter the
name before a rename. Preserve populated values alongside the resulting folder/name;
these describe the file, while `ActionType` describes the activity and
`InitiatingProcessUniqueId` identifies the initiating process. Confirm Defender for Endpoint
collection, the deployed action vocabulary and actual column population; missing prior-name
fields do not exclude renames. See the [native file-event schema](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-devicefileevents-table).
Count distinct affected artifacts and successful versus failed operations, not just rows.
With older process data, require PID plus creation time.

Sysmon 11 is create/overwrite, and 23/26 concern deletion; these are not a complete
rename or in-place write history. Gaps must constrain any affected-file estimate.
Service Control Manager 7036/7040 can add state/configuration context, but backup
maintenance also changes services. A command mentioning a recovery control does not
prove its removal: seek the control provider's operation outcome and independent backup
availability evidence. Keep encryption, deletion and recovery impairment as separate claims.
