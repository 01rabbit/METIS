# Preserve evidence without obscuring acquisition limits

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

Artifacts or live state may be needed to support technical conclusions, response decisions or later review.

## Responsibilities

The evidence custodian records handling and access; qualified collectors choose acquisition methods; the incident owner balances collection against current harm and service impact.

## Work and decision records

1. Document collection authority, scope, device/account identifiers, time and intended questions. Avoid collecting unrelated personal or secret data when it does not support the task.
2. Choose live versus offline acquisition according to volatility, encryption, availability and urgency. There is no universal collection order that overrides physical safety or ongoing harm.
3. Record tool/version, commands or method, start/end times, errors and side effects. Preserve originals and analyze controlled copies; capture companion data such as a database WAL when required.
4. Hash acquired artifacts and record their extent. A hash establishes equality of the acquired bytes; it does not prove completeness, trustworthy origin or an accurate system clock.
5. Track every transfer, handler, storage location and access change with timestamps. Use encryption and access controls appropriate to the evidence.
6. Validate parser prerequisites and output coverage before relying on results. A tool exit code alone is not proof of a complete acquisition or a clean artifact.
7. Apply retention, legal hold and disposal decisions through the responsible owner. Keep evidence and credentials outside Git and outside generic skill content.

## Completion evidence

The evidence register allows a reviewer to identify what was acquired, how it changed hands, what was excluded and how each finding was derived. Any missing, damaged or nonrepeatable evidence is explicit.

## Tabletop check

Tabletop a truncated image, an acquisition interrupted by urgent containment, a missing WAL and a transfer with a hash mismatch. Verify that these conditions affect conclusions and are not silently repaired in the original.

## Concrete observation contract

Record acquisition ID, original locator, host/device identity, collector/tool version,
start/end UTC time, clock offset, authority, method, byte size, digest algorithm/value
and handling history. A hash compares the acquired bytes; it does not prove a complete
or truthful source. Keep working copies separate from originals and record every
transformation with input/output digests.

Windows event files commonly reside under `%SystemRoot%\System32\winevt\Logs`;
preserve channel/provider context. Machine registry hives commonly reside in
`%SystemRoot%\System32\config\`; a user's `NTUSER.DAT` and
`AppData\Local\Microsoft\Windows\UsrClass.dat` have different scopes. Preserve associated
transaction logs. Filesystem metadata such as `$MFT` and `$Extend\$UsnJrnl` may be
included in an authorized volume image and is not ordinary application log data.
Linux runtime observations under `/proc` are volatile; `/var/log/`, `/etc/` and the
effective timezone configuration answer different questions. These are acquisition
locators, not a claim that METIS parses every format.

Acquire SQLite databases with a consistent snapshot and required WAL/SHM sidecars;
copying only a live main file can omit recent state. Choose volatility order against
actual system safety and evidence value. Document what a shutdown/isolation would lose
without delaying proportionate authorized protection solely to complete collection.
