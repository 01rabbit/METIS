# Live collection: where to look and what to preserve

Use only an approved remote session and available read tools. The bundled SSH adapter has a
bounded action set; this table does not imply it accepts arbitrary shell or PowerShell commands.
Record collector/host UTC, OS build, access errors and the identity of each observation. Plan
privileged collection or any modification with the owner. Never dump credential/environment
contents into ordinary notes.

## Linux: bind volatile fields to one host and boot

| Location or observation | Exact values | Correlation and limits |
| --- | --- | --- |
| `/proc/sys/kernel/random/boot_id` and `/proc/stat` | Boot UUID; `btime` in Unix epoch seconds when available | Qualify PID identity and timestamp conversion with the boot; a reboot invalidates cross-boot PID joins |
| `/proc/{pid}/stat` | PID, parent PID and `starttime` (field 22, clock ticks since boot) | Convert ticks using `sysconf(_SC_CLK_TCK)` from the observed system; relate boot seconds + start ticks / ticks-per-second with clock uncertainty. Parse the parenthesized command before counting fields |
| `/proc/{pid}/status` | `Name`, `State`, `Pid`, `PPid`, `Uid`, `Gid`, `NSpid` when present | Each Uid/Gid sequence is real, effective, saved-set and filesystem ID, in that order; container-visible IDs may differ from host IDs |
| `/proc/{pid}/cmdline`, `exe`, `cwd` | NUL-separated arguments; executable and current-directory link targets | A rendered command line loses NUL boundaries. A deleted executable may be a legitimate upgraded program |
| `/proc/{pid}/maps` | Address interval, permissions, file offset, device, inode and pathname | Executable anonymous/memfd mappings are leads; they are not an automatic malicious verdict |
| `/proc/{pid}/fd` with socket inventory | Descriptor link and `socket:[inode]`; local/remote addresses, ports, state and process ownership from a supported collector | Use host/namespace, inode and collection time; `/proc/{pid}/net` describes that network namespace, not only that process |

The layouts and namespace caveats are defined in the [Linux proc documentation](https://www.kernel.org/doc/html/latest/filesystems/proc.html).
Process and socket observations are changing snapshots; join failures can be races or permission
gaps. A compromised kernel can falsify both views. Supplement them with independent telemetry.

For persistence and authentication, collect the actual resolved service, cron, loader, SSH and
account-policy files identified in [Linux artifacts](../../soc-host-forensics/references/linux-artifacts.md).
Do not assume vendor-unit directories or home directories are universal. Preserve effective
configuration, include/drop-in provenance and user/system scope alongside a suspicious value.

## Windows: correlate exact CIM fields, not display labels

| Read surface | Fields to retain | Join or follow-up |
| --- | --- | --- |
| `Win32_Process` through an approved CIM reader | `ProcessId`, `ParentProcessId`, `CreationDate`, `ExecutablePath`, `CommandLine` | Qualify PID by host and creation interval; parent PID can already refer to a later process |
| `Get-NetTCPConnection` where available | `LocalAddress`, `LocalPort`, `RemoteAddress`, `RemotePort`, `State`, `OwningProcess` | Link to a process observed at the same time; a socket does not identify transferred bytes |
| `Win32_Service` | `Name`, `DisplayName`, `PathName`, `StartName`, `StartMode`, `State`, `ProcessId` | Name is the service identifier; PathName is its configured executable/arguments. Compare the configuration with the running image |
| Registered task export | Task path/name; XML `Actions/Exec/Command`, `Arguments`, `WorkingDirectory`; `Principals/Principal/UserId` and `RunLevel` | Preserve the registered definition and execution events; registration or enabled state is not an execution record |
| Event/registry collection | Actual EVTX channel/file and hive/profile paths from the [Windows reference](../../soc-host-forensics/references/windows-artifacts.md) | Preserve native files or a verified export, acquisition time, hashes and collection failures |

Primary definitions: [Win32_Process](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process),
[Win32_Service](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-service),
[TCP connection properties](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-nettcpconnection)
and [Task Scheduler schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema).

## Transport observations are not incident conclusions

Record the connection profile ID, verified endpoint identity, route/DNS context, client version,
resource lease, acquisition start/end and transport result. Store secret references separately.
For a file transfer retain the remote logical path, local path, expected/received byte counts,
completion result and compared digests. A stable size alone is insufficient because files can
be preallocated. Session loss leaves acquisition unresolved until reconciled.

Use [evidence locators](../../soc-triage/references/evidence-locators.md) for the private manifest.
If a read fails, name the unavailable surface and privilege instead of returning an empty result.
