# Investigate link and library artifacts as execution or access leads

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a user-facing shortcut or library reference cause unexpected network access or execution?

## Evidence to request

Acquired artifact hash and parsed target metadata; original delivery context; file association/shell events; process, network and authentication records.

## Reasoning procedure

- Parse the acquired structure without opening it through the desktop shell. A target path in the artifact describes potential behavior, not an observed action.
- Distinguish local launch targets, remote file references and icon/metadata retrieval. A network access can occur without the main target being executed.
- Associate observed access with the relevant shell process, user session and artifact exposure. A remote connection alone does not prove a user double-click.
- Inspect authentication consequences separately from execution. Resolving or browsing a reference can create authentication telemetry without proving credential compromise.

## Alternatives and limits

Enterprise shortcuts, shared libraries and centrally managed icons commonly reference network resources. Artifact timestamps and recent-item records have different update semantics.

## Discriminating checks

Test inert parsed metadata for a local target, an approved share, an inaccessible remote resource and attributable execution. Do not activate the artifact. Quarantine or share blocking requires the response owner.

## Concrete observation contract

Preserve the acquired `.lnk`, `.library-ms` or `.searchConnector-ms` file and any
`Zone.Identifier` stream without opening it in the shell. A remote reference inside the
file indicates possible behavior, not that a user activated it. Sysmon 11 can associate
`TargetFilename` with its writer `ProcessGuid`; event 15 can add stream evidence. Event 1
and the resulting parent/child GUID relation are needed to assess later execution, and
event 3 can add a collected network connection. Those sources require their configured
filters and are not implied by possession of the shortcut.

For PowerShell 4104 in Microsoft-Windows-PowerShell/Operational, assemble fragments by
host and `ScriptBlockId`, accounting for `MessageNumber`/`MessageTotal`, before interpreting
script content as a whole. Keep incomplete blocks marked incomplete. Link the process,
artifact identity and script record explicitly; timestamp proximity alone is insufficient.
