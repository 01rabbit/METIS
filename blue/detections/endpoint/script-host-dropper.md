# Relate script execution to newly written artifacts

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has a script process created an artifact that was subsequently used for an unexpected purpose?

## Evidence to request

Script/interpreter process identity, input script reference, file-write records and hashes, rename history, later execution/load events, user and deployment context.

## Reasoning procedure

- Connect the write to the exact process and resulting artifact. A script command line mentioning a path does not prove a write occurred.
- Separate creation from subsequent execution or loading. Preserve script-versus-native execution semantics when matching the produced artifact.
- Handle rename, overwrite and hash changes explicitly. Reusing a path does not guarantee the produced and executed bytes are identical.
- Review network acquisition, persistence registration or unusual descendants as corroboration without requiring a specific tool name.
- Track temporary-file cleanup as missing evidence rather than declaring no artifact existed.

## Alternatives and limits

Software installers, logon scripts, packaging and developer workflows create then launch files. Common interpreter names and writable directories are weak signals by themselves.

## Discriminating checks

Test a legitimate installer, a write without execution, a renamed artifact, an overwritten path and a correctly joined anomalous chain. Use inert metadata fixtures; acquired scripts must not be run. File deletion or quarantine requires scoped authority.

## Concrete observation contract

Use Sysmon 11 `TargetFilename` with writer `ProcessGuid` for a collected create/overwrite,
then Sysmon 1 for the later process lifetime. For an interpreted script, the created
process image is the interpreter; its input-script reference, not `Image` alone, relates
the written artifact to execution. Preserve hashes, rename/overwrite history and path
normalization instead of assuming that equal paths contain the same bytes.

Sysmon 15 may provide alternate-stream provenance; missing `Zone.Identifier` is not
proof of local origin. Events 3 and 22 can add network/DNS evidence when configured, but
acquisition and later execution need independent observations. A source URL in a command
line does not prove a download succeeded. An installer that writes a script without ever
running it must not satisfy the full write-to-execution chain.
