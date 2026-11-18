# Investigate access to credential-bearing resources

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does an unusual reader have corroborating evidence of collecting credentials or exporting a credential-bearing object?

## Evidence to request

Process-access or EDR read telemetry; source/target process identities and access masks; file creation; registry/object auditing where enabled; image trust; approved diagnostic activity.

## Reasoning procedure

- Separate LSASS access, registry-hive collection, directory database access and user credential stores. They have different collection requirements and affected identities.
- Decode the recorded access rights instead of matching one hexadecimal mask. An opened handle establishes granted capability; it does not establish the bytes read.
- Connect the reader to resulting files, memory acquisition evidence or follow-on authentication. A filename ending in a dump extension does not identify its contents.
- Preserve source process ancestry and module context. Incomplete stacks and unresolved symbols are uncertainty, not a unique signature for evasive execution.
- Assess credential exposure for the observed host/session population; do not infer every domain credential was stolen.

## Alternatives and limits

Security agents, crash handlers, backup tools and administrators may access these objects. Registry reads are not supplied by Sysmon registry-change events. Missing configured access telemetry prevents a clean result.

## Discriminating checks

Test a permitted diagnostic reader, an unusual handle without a read, and an unusual reader with a verified credential-bearing output. Ensure the report distinguishes access from collection. Secret rotation or process termination needs a scoped response decision.

## Concrete observation contract

Sysmon 10 can associate an accessing process with the LSASS target through source/target
process GUIDs, `GrantedAccess` and `CallTrace` when collected. Verify exact field casing
with the installed schema. A granted handle access mask describes capability; it does
not prove that credentials were read or persisted. Security tools and diagnostics often
open such handles legitimately.

Follow any suspected artifact with Sysmon 11 `TargetFilename` and writer `ProcessGuid`,
acquisition metadata and a hash. For audited file or registry use, Security 4663 needs
`ObjectType`, `ObjectName`, `AccessMask`, `ProcessId` and `SubjectLogonId`, as well as the
required object auditing/SACL. Decode the rights before calling it a read. Sysmon 12/13
are registry mutations and cannot substitute for read evidence. Lack of an output file
leaves collection unknown; it does not establish that no access occurred.
