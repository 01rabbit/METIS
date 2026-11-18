# Host and memory parser integrity

Use this alongside the Windows, Linux and memory references. This is an analysis checklist;
METIS does not include the specialized acquisition and parsing programs described here.

## Windows events and time

Read the direct provider, EventID and named EventData fields from the same XML record.
System/Task is a category and need not be a scheduled-task name. A number found anywhere
in XML is not an EventID. Avoid regex-only XML extraction. Disable DTD/external entities;
validate UTF-8/UTF-16, duplicates, bounded nesting and input size. Account for malformed and
skipped records. An unavailable parser is not an empty channel.

Preserve SystemTime's UTC and up to 100 ns precision where present. GUI timezone and parser
microsecond truncation can change an exact answer. Record clock offset and uncertainty;
timestamp agreement alone does not establish causality. An EVTX backend can skip recoverable
records, so compare channel counts and selected raw records using an independent parser.

Read an immutable snapshot and detect input replacement, truncation and mutation. Bound
file size, records, output and total I/O. Per-file read limits do not bound repeated reads
or aggregate work. Never accept a partial parse as proof of absence.

## Registry, execution and activity

Prefetch execution times come from the internal run-time array, not the file mtime.
Validate layout versions and compressed MAM framing/checksum support before interpreting.
For a dirty registry hive, preserve original hive/log files and replay the correct ordered
transaction sequence onto a copy. Verify digests and a known recent sentinel record.
An unreplayed Amcache hive can omit the event being investigated.

Correlate Sysmon using ProcessGuid plus host; a PID can be reused. Preserve logon-session
IDs and lifetime. A logon event and a session start in the same second can still be different
events. Compare MFT standard-information and filename timestamps with copy semantics and
filesystem context before claiming timestomping.

LNK, jump lists, Activities records and UNC paths show different kinds of interaction.
WLAN connection records distinguish the connected BSSID from nearby scanned access points.
VM display names differ from configuration and disk-image filenames. Program runtime requires
process or execution telemetry; unique filesystem times do not define its start and end.

For network-usage questions, distinguish decimal KB from KiB and preserve exact rounding.
For RDP bitmap caches, reconstruct tile placement, dimensions and z-order from evidence.
An arbitrary montage is not the desktop. Record OCR crop coordinates and verify raw pixels.

## API traces, executables and identifiers

Identify container headers before decoding API traces. Separate process metadata, call
records and data buffers. Respect pointer width, file-relative offsets and bounded spans;
replay an exact call selector from the original artifact. A name in an index is not proof
that the call executed successfully.

Hashes have domains: full-file bytes, Authenticode image digest, imports and fuzzy hashes
are not interchangeable. Corroborate with independent sources rather than circular reports.
Keep file offset, relative virtual address and virtual address separate. Map strings to
code/data references before describing runtime behavior.

A hidden file may still be visible by direct metadata lookup even if a compromised userspace
listing omits it. Prefer offline acquisition or trusted tooling and compare directory entries,
metadata, loaded libraries and process mappings. Do not execute a suspected rootkit.

## Memory-image analysis

Validate image type, architecture, size and symbol compatibility before a plugin run.
Preflight success does not answer the investigation. Select an objective-specific sequence:
process ancestry, connections, command lines, modules, persistence and suspicious regions.
Preserve full image identity and parser/tool receipts.

Use a fresh private symbol cache. Offline processing should remain offline; an approved
symbol download needs an identified trusted endpoint and integrity controls. Missing-symbol
errors on stderr invalidate an otherwise empty result, even when exit status is zero.
Separate unsupported plugins, truncated output and parser failure from genuine negatives.

Bound each plugin's elapsed time, memory, output and aggregate I/O. Plugin inventories vary
by version; do not imply unavailable capabilities. A combined timeline may repeat facts from
its source plugins: duplicates are not independent corroboration. Preserve conflicts with
the more specific source record instead of silently choosing one.

A suspicious memory region, executable permission or injection heuristic needs validation
against legitimate JITs and security agents. Work on extracted private copies. No crash or
child process is required for an intrusion, so absence needs coverage of connections, file
access, process ancestry and memory; no individual sensor proves the whole host clean.

## Unix authentication

Traditional auth/syslog timestamps may lack year and timezone. Infer them from acquisition
context and adjacent authoritative records, recording the uncertainty. utmp/wtmp uses a
different representation; correlate accepted SSH authentication, PAM and session records
without counting each line as another login. Repeated PID, username or second-level time
alone is not a session key.

## Acquisition-generated inventory files

For AChoir's configuration at revision `6acdebbcdd20daf9423302999a30fcc5643c2c02`, these are relative acquisition-output candidates:

| Relative member | Recorded observation role |
| --- | --- |
| `Info.dat` | PSInfo system/software inventory output |
| `SYS/IPConfig.dat` | IP configuration snapshot, including adapter configuration |
| `SYS/IPCfgDNS.dat` | Resolver-cache display at collection time |
| `SYS/NetBios.dat` | NetBIOS name/cache/session observations emitted by the configured collector |
| `Arn/AutoRun.dat` | Autorunsc inventory output; this revision requests CSV representation despite the `.dat` suffix |

Resolve the actual acquisition root, collector revision/configuration and command status before using those paths. Customized and older configurations can use other directories. Keep file/member hashes and original text/encoding; extension alone does not define a binary format or a stable column schema. A collection-time address, cached name, installed component or autorun entry does not establish its incident-time state or execution. Acquisition output is not an independent second event when it repeats the same underlying state.
[Versioned acquisition configuration](https://github.com/OMENScan/AChoir/blob/6acdebbcdd20daf9423302999a30fcc5643c2c02/AChoir.ACQ). Inspect supplied output; do not execute the configuration as an analysis step.

## Collector MFT cache coordinates

AChoir at the same revision constructs `{resolved-cache-directory}/{volume-letter}-MFT.db`; `C-MFT.db` is the C-volume example. Resolve the cache setting and volume from the acquisition, rather than assuming that an export directory is a native Windows path. This is a collector SQLite cache, distinct from raw `$MFT` bytes.

| Table/coordinate | Contract observed in this revision |
| --- | --- |
| `FileNames.MFTFilesRecID` and `MFTFiles.RecID` | The reader joins these values. Both are declared INTEGER; `MFTFiles.RecID` is a generated primary key, not a raw NTFS record reference. |
| `FileNames.FullFileName`; `MFTFiles.FileName`, `MFTRecID`, `MFTPrvID` | Preserve full-name, basename and raw stored record/parent identifiers separately. The name columns have no declared SQLite type. Retain volume/database scope. |
| `MFTFiles.FileDateTyp` | The reader selects FN values when the first two characters match `FN` case-insensitively; otherwise it reads SI values. This branch is not validation that every other stored marker is meaningful. |
| `MFTFiles.FNCreDate`, `FNAccDate`, `FNModDate`; `SICreDate`, `SIAccDate`, `SIModDate` | These six columns have no declared SQLite type. Preserve actual storage classes and distinguish the filename and standard-information families. |

The [versioned cache reader](https://github.com/OMENScan/AChoir/blob/6acdebbcdd20daf9423302999a30fcc5643c2c02/AChoir.cpp) consumes decimal strings for those clocks as unsigned counts and splits them into a FILETIME structure. For a validated normal value, [FILETIME](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-filetime) uses 100-nanosecond intervals from `1601-01-01T00:00:00Z`. Preserve malformed, missing and sentinel values; this reader contract does not validate an arbitrary exported database or its writer. Rows and timestamps alone do not prove execution, intentional tampering or a complete filesystem inventory. METIS adds no dedicated cache decoder here.
