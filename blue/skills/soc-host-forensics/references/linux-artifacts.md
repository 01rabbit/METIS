# Linux and container evidence

## Authentication and execution

Inventory distribution, boot history, journal retention, audit configuration and timezone.
Authentication may reside in the journal, auth/security files and rotated compressed logs.
Combine SSH acceptance/failure, PAM, sudo and session records without counting every line as
a distinct login. Missing year/zone in syslog requires an explicit inference.

Use audit serial/time and host/boot context to join SYSCALL, EXECVE, CWD and PATH records.
An argv record alone lacks some outcome and identity information. Journals, endpoint sensors
and process accounting can corroborate execution; no single facility guarantees full history.

Shell history may be edited, deferred until exit, missing timestamps or absent for noninteractive
sessions. Inspect history configuration and account context before assigning completeness.
Check wtmp/utmp/btmp interpretation against their native time representation.

## Files, recovery and persistence

Compare inode metadata with content, ownership, package records and backups. mtime/ctime
differences have normal explanations such as permission changes and copies. ctime is not a
tamper-proof clock under all attacker privileges. atime depends on mount policy.

Where original content has been restored or deleted, consider editor registers, swap/undo,
application backups, account-file backups, snapshots and journal residue. Preserve provenance;
a deleted fragment can belong to an older unrelated version. Avoid copying password hashes
into reports when only account identity or password-change time is needed.

Use offline image-aware tools for unallocated data. A raw device scan must have bounded
buffers, observable errors and a positive control; OOM or partial reads must not become
“zero matches.” Search a known data representation, not only a guessed original filename.

Inspect the mechanisms relevant to the incident: system/user services and timers, cron/at,
startup scripts, shell profiles, authorized keys, SSH command hooks, dynamic loader settings,
PAM modules, sudo policy, capabilities, SUID/SGID, udev and kernel module loading. A locally
managed unit without package ownership is not automatically malicious.

## Web and container context

Relate application writes and worker processes to access/error logs and deployment history.
A successful HTTP response after failures does not prove a web shell or successful discovery.
Keep proxy socket addresses separate from forwarded client claims and account for trusted
proxy configuration.

For containers record image digest, writable-layer changes, mounts, capabilities, namespaces,
runtime logs and orchestrator events. Privileged settings or a runtime socket mount increase
host exposure but do not themselves prove a host compromise. A removed file may remain in an
image layer; distinguish image history from current writable state.

Cloud-init and instance bootstrap records can explain first-boot actions. Metadata-service
traffic is common in legitimate agents; assess originating process, requested resource,
credential use and cloud audit before asserting theft.

Finish with a bounded UTC timeline, identity/session mapping, configuration changes and
coverage gaps. For live collection use soc-remote-triage; for memory use the memory guide.

## Evidence locations and native fields

Resolve paths inside the acquired host root, not on the analyst workstation. Distribution,
logging configuration, user home lookup, retention and container mount layout can change the
locations below. Retain the actual path, source hash and record coordinate using the
[evidence locator contract](../../soc-triage/references/evidence-locators.md).

| Surface / discovery location | Values to preserve | Correlation and result boundary |
| --- | --- | --- |
| Text authentication logs: commonly `/var/log/auth.log` or `/var/log/secure`, their rotations, and the configured syslog destinations | Original timestamp, program/PID, account, authentication method, peer address/port and message outcome; public-key fingerprint if actually logged | A PID plus host and short interval helps connect SSH/PAM stages. Accepted credentials, session creation and command execution are different observations; connection drops are not automatically failed passwords |
| Journal storage under `/var/log/journal/` or `/run/log/journal/` when enabled | `__CURSOR`, `_MACHINE_ID`, `_BOOT_ID`, `_HOSTNAME`, `_SYSTEMD_UNIT`, `_PID`, `_UID`, `_EXE`, `SYSLOG_IDENTIFIER`, `MESSAGE` | Cursor identifies an entry; preserve boot/machine context for joins. A text export and the native journal can be two representations of one event; not two independent witnesses |
| Journal clocks | `__REALTIME_TIMESTAMP` is receipt time in UTC epoch microseconds; `_SOURCE_REALTIME_TIMESTAMP` is an available earlier source time in the same unit; `__MONOTONIC_TIMESTAMP` is receipt monotonic microseconds | Pair monotonic time with `_BOOT_ID`; do not treat it as an absolute UTC epoch. Missing source time stays unknown. Wall-clock adjustment can affect ordering |
| Audit destination from `/etc/audit/auditd.conf` `log_file`, commonly `/var/log/audit/audit.log` | `type`, optional `node`, and `msg=audit(seconds.fraction:serial)`; Linux v6.12 formats Unix seconds since 1970-01-01 UTC followed by three decimal millisecond digits, then the event serial | Join records sharing event timestamp/serial within the same host and boot/collection context. Count assembled events separately from `SYSCALL`, `EXECVE`, `CWD` and `PATH` rows. The serial is an identifier, not a fractional time component; wall-clock corrections can disturb order. [Kernel formatter](https://github.com/torvalds/linux/blob/v6.12/kernel/audit.c), [realtime clock](https://www.kernel.org/doc/html/v6.12/core-api/timekeeping.html) |
| Audit `SYSCALL` / `EXECVE` | `arch`, `syscall`, `success`, `exit`, `pid`, `ppid`, `auid`, `uid`, `euid`, `ses`, `comm`, `exe`, `key`; argument `argc`, `a0`, `a1` and subsequent members | Syscall numbers require the recorded architecture. `auid` is login identity, not necessarily current UID; unset identity is not root. Argument data can be encoded/fragmented; retain raw bytes and the decoder used. No configured rule means no promised execution coverage |
| Audit `CWD` / `PATH` | `cwd`; `item`, `name`, `inode`, `dev`, `mode`, `ouid`, `ogid`, `nametype` | Use CWD for a CWD-relative operation such as `openat` with `AT_FDCWD`; a different `dirfd` needs the same process instance's directory descriptor and namespace context. Keep unresolved paths relative. Several PATH rows may describe one operation; check the syscall result |
| Binary sessions, commonly `/var/run/utmp`, `/var/log/wtmp`, `/var/log/btmp` | Native `ut_type`, `ut_pid`, `ut_line`, `ut_id`, `ut_user`, `ut_host`, `ut_session`, `ut_tv.tv_sec`, `ut_tv.tv_usec`, `ut_addr_v6` where supported | Parse the source ABI, not a hardcoded universal record size. `USER_PROCESS`, `DEAD_PROCESS` and boot records have different roles. `tv_sec` is epoch seconds with microseconds separately; join host/boot/session/terminal before deriving duration |
| Shell history selected by `HISTFILE`, often `.bash_history` in the user's home | Original line order, optional timestamp marker, full command boundaries, shell/version and `HISTCONTROL`/`HISTIGNORE` context | Bash saved timestamps use the history comment character followed by epoch seconds; multiline entries need the actual format. History may be filtered or delayed until shell exit; missing history is not itself proof of deletion or execution |
| Process accounting selected by the installed accounting service | Source file/ABI and `ac_comm`, `ac_uid`, `ac_gid`, `ac_btime` (epoch seconds), `ac_etime` when exposed by that format | Accounting normally records a process on termination; it does not preserve complete argv. Compressed numeric representations require a matching decoder, and absent accounting is a coverage gap |

Primary definitions: [journal fields](https://www.freedesktop.org/software/systemd/man/latest/systemd.journal-fields.html),
[audit configuration](https://man7.org/linux/man-pages/man5/auditd.conf.5.html),
[audit events](https://man7.org/linux/man-pages/man8/ausearch.8.html),
[native audit fields](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/risk_reduction_and_recovery_operations/auditing-the-system),
[utmp layout](https://man7.org/linux/man-pages/man5/utmp.5.html),
[Bash history](https://www.gnu.org/s/bash/manual/html_node/Bash-History-Facilities.html)
and [process accounting](https://man7.org/linux/man-pages/man5/acct.5.html).

## Resolve configuration, then compare it with activity

| Mechanism / locations to inspect | Configuration fields or coordinate | Validation and limitation |
| --- | --- | --- |
| System units: `/etc/systemd/system/`, `/run/systemd/system/`, vendor directories such as `/usr/lib/systemd/system/`; user units under `$XDG_CONFIG_HOME/systemd/user/` (normally `~/.config/systemd/user/`) and configured search paths | Unit name, selected fragment path, all drop-ins and symlink targets; service `ExecStart`, `User`, `Group`, `EnvironmentFile`, `WorkingDirectory`; timer `OnCalendar`, `OnBootSec`, `OnUnitActiveSec`, `Unit` | Resolve precedence and effective unit data; a unit file or enabled link proves configuration. Correlate its journal/process activity to establish a run. Local, unpackaged units can be legitimate |
| Cron: `/etc/crontab`, `/etc/cron.d/`, periodic directories and distribution-specific per-user spool such as `/var/spool/cron/` or `/var/spool/cron/crontabs/` | Minute, hour, day-of-month, month, day-of-week; system-crontab user field; command, `SHELL`, `PATH`, `MAILTO`, `CRON_TZ` when supported and file ownership | Per-user entries lack the system user column. Cron and anacron schedules are different; file presence does not establish that a job ran. Inspect output routing and mail delivery before treating an empty output file as silence |
| Login and shell startup files selected for the actual shell/account | `/etc/profile`, `/etc/profile.d/`, account `.profile`/`.bash_profile`/`.bashrc`, and relevant system shell configuration | Interactive/noninteractive and login/nonlogin shells consult different files. Record include order; a string in an unused file does not establish execution |
| SSH service and account authorization | `/etc/ssh/sshd_config`, included files, effective `Match` scope, `AuthorizedKeysFile`, `AuthorizedKeysCommand`, `ForceCommand`, `PermitRootLogin`; configured authorized-key file and entry options | Resolve `%h`, `%u` and home-relative paths for the real account. Distinguish server authorization from client `.ssh/config`; a configured forced command still needs a matching authentication/session trace |
| Accounts and privilege policy | `/etc/passwd` fields 1/3/4/6/7: name, UID, GID, home, shell; `/etc/shadow` field 3: password-change day count since 1970-01-01; `/etc/sudoers` and configured includes, often `/etc/sudoers.d/` | Compare identities and policy with retained backups such as `/etc/passwd-` only when acquired. Shadow 0 has force-change semantics and empty values differ. Keep password hash fields out of notes; UID 0 alone does not establish an unauthorized change |
| Loader, PAM, devices and modules | `/etc/ld.so.preload`; `/etc/pam.d/` service stack; `/etc/udev/rules.d/` and vendor rules; `/etc/modules-load.d/` and vendor configuration | Preserve selected library/module, ordering, ownership and package baseline. Configuration or a loaded object is not a demonstration of malicious behavior. Do not load suspected modules to test them |
| Additional startup surfaces, if installed | `/etc/rc.local`, `/etc/init.d/`, `/etc/rc*.d/` links, distribution at-job spool, and `/etc/update-motd.d/` where supported | Read effective service links, job owner/schedule and invoked file. These mechanisms are installation-dependent; directory existence does not establish enabled execution |
| Filesystem privilege attributes | File inode/mode and owner; `S_ISUID`, `S_ISGID`; `security.capability` extended attribute decoded for its supported revision | Record applicable mount and namespace context, effective rights and baseline. Presence indicates a privilege mechanism, not a successful unauthorized transition |
| Metadata and recovery residues | Filesystem device/volume and inode, size, mode/UID/GID, atime/mtime/ctime and birth time if supported; editor configuration for `.viminfo`, swap/backup/undo locations | ctime is metadata-change time, not creation time or a tamper-proof guarantee. atime depends on mount policy. Editor registers/fragments and backups may describe an older revision; attach the exact source coordinate, not an assumed incident date |
| Software/deployment and bootstrap records | Distribution package database and transaction logs, for example `/var/log/dpkg.log` and `/var/log/apt/history.log` on applicable systems; configured application access/error logs; `/var/log/cloud-init.log`, `/var/log/cloud-init-output.log`, instance data under `/var/lib/cloud/` | Installation, service startup and HTTP outcome are different events. User data and configuration may contain secrets; retain restricted references. Metadata-service traffic also has legitimate callers |
| Container engine evidence | Actual engine data-root and logging driver; inspect metadata `Id`, `Image`, `Config.Image`, `State.Pid`, `HostConfig.Privileged`, `HostConfig.PidMode`, `HostConfig.Binds`, `HostConfig.CapAdd`, `Mounts`, `LogPath` when supplied by Docker | Image ID/digest differs from a tag string. A privileged setting or host mount describes exposure; host compromise requires observed effects. Storage-driver directories and JSON log paths are not universal defaults |

Primary definitions: [unit search paths](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html),
[service properties](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html),
[cron](https://man7.org/linux/man-pages/man5/crontab.5.html),
[SSH configuration](https://man.openbsd.org/sshd_config),
[account fields](https://man7.org/linux/man-pages/man5/passwd.5.html),
[shadow dates](https://man7.org/linux/man-pages/man5/shadow.5.html),
[inode times](https://man7.org/linux/man-pages/man7/inode.7.html),
[cloud-init logs](https://docs.cloud-init.io/en/23.1.1/reference/faq.html)
and [Docker inspection](https://docs.docker.com/reference/cli/docker/inspect/).
When interpreting captured shell output, apply redirections in their original left-to-right order: duplicating a descriptor preserves its destination at that point, not a later destination. Missing mail delivery or stderr coverage is a collection limit. See [Bash redirection semantics](https://www.gnu.org/s/bash/manual/html_node/Redirections.html), [relative directory descriptors](https://man7.org/linux/man-pages/man2/open.2.html) and [file capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html).
For volatile procfs paths, PID start ticks and namespace socket joins use
[live collection](../../soc-remote-triage/references/live-collection-fields.md).

## 初期ブート・デスクトップ索引・package manifest

初期ブートの対象は、取得した bootloader 設定が選ぶ kernel と initramfs の組で固定する。
`/boot/initramfs-{release}.img` や `/boot/initrd.img-{release}` は探索候補であり、
実際には kernel 内蔵 archive や別の image に含まれる構成もある。cpio member の `/init`、
symlink、module、起動設定を実行せず読み、順序・圧縮層・上書きを保持する。
[initramfs の定義](https://docs.kernel.org/filesystems/ramfs-rootfs-initramfs.html)。

「auditd より早い」だけで audit event の発生不能を断定しない。取得した kernel command line
の `audit`、`audit_backlog_limit`、実際の rule/sensor activation、queue loss と保持期間を確認する。
`audit=1` は userspace auditd が本格的に有効化する前にも限定数の記録を RAM に保持し得る。
初期ブートを通常ログが覆わない場合は image/member hash、信頼できる取得経路の package/build
記録、boot measurement を補助にする。package DB 自体の真正性と版を確認し、TPM の PCR 番号や
測定対象を全 firmware/bootloader に共通と仮定しない。
[kernel audit parameters](https://docs.kernel.org/admin-guide/kernel-parameters.html)。

GNOME Tracker3 / LocalSearch がある取得物では、使用版、ユーザー、XDG cache 設定と indexer の
収集範囲を先に確認する。`~/.cache/tracker3/files` とその退避世代は候補であり、固定の DB 名・table
配置を仮定しない。domain-ontology rule を用いる版は、インストール済み data directory の
`domain-ontologies/*.rule` にある `DomainOntology` / `CacheLocation` と実際の XDG 設定から所在を解決する。
RDF 表現では `tracker:FileSystem` graph の `nfo:FileDataObject` と content graph の
`nie:InformationElement` を区別し、resource URI、predicate、native value/type、graph と取得世代を記録する。
索引中の名前や metadata は元ファイル本文、実行、削除、持出しの証明ではない。更新遅延・未接続媒体・
再構築や除外設定も検討する。[LocalSearch の graph](https://gnome.pages.gitlab.gnome.org/localsearch/endpoint.html)、
[cache の退避](https://gnome.pages.gitlab.gnome.org/localsearch/corruption.html)、
[rule の所在解決](https://github.com/GNOME/localsearch/blob/master/src/libtracker-miners-common/tracker-domain-ontology.c)。

opkg を使う image では、対象 root と package destination に対応する info directory を解決する。
`/usr/lib/opkg/info/{package}.list` は OpenWrt 系での候補であり、記載された file path と package の関係を
表す manifest。元 manifest の行、取得 root 内に解決した path、実物の type/hash を分ける。
manifest にないファイルも生成物・更新・overlay・管理者設定で説明でき、記載されたファイルにも変更はあり得る。
manifest は各内容の hash による真正性証明ではなく、欠損した収集範囲の差分を侵害へ直結させない。
[opkg の file list 処理](https://github.com/openwrt/opkg-lede/blob/master/libopkg/pkg.c)、
[destination 解決](https://github.com/openwrt/opkg-lede/blob/master/libopkg/pkg_dest.c)、
[OpenWrt の manifest 所在例](https://openwrt.org/user/vvkjndl/opkg-list-packages-sorted)。

## Layer views and native session-record limits

In OCI image changesets, `.wh.{basename}` is a whiteout for the corresponding lower-layer path.
The opaque marker `.wh..wh..opq` suppresses lower-layer children beneath its directory.
Markers belong to layer application semantics and are hidden from the resulting filesystem view;
a flattened view can therefore omit bytes that remain in an acquired earlier layer. Preserve the
manifest/layer digest, member path and layer order separately from the merged path. Neither a
marker nor historical file content proves that a running container used that content or that a
particular actor deleted it. See the [OCI v1.1 layer specification](https://github.com/opencontainers/image-spec/blob/v1.1.0/layer.md).

In the cited glibc layout, `utmp` provides host/address fields such as `ut_host` and `ut_addr_v6`,
while `lastlog` contains `ll_time`, `ll_line` and `ll_host`; neither defines a source-port field.
Resolve the acquired platform ABI and native types before decoding. A port absent from these
records is a schema limitation, not proof that a connection lacked a port. Obtain connection
telemetry when the port is needed; do not invent it from a rendered host string.
[glibc record definitions](https://github.com/bminor/glibc/blob/master/bits/utmp.h).

## Versioned process-accounting clock units

Linux v6.12 writes `ac_version` as the format version combined with the byte-order flag: bit `0x80` denotes big-endian, while a clear bit denotes little-endian. Resolve the acquired ABI and version before decoding a record. In `acct_v3`, `ac_pid`, `ac_ppid`, `ac_uid`, `ac_gid` and `ac_btime` are unsigned 32-bit fields. `ac_btime` is epoch seconds; the writer derives it at record creation from wall time minus elapsed whole seconds. It is not an independent immutable start clock.
[Native layouts](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/acct.h).

In that version's format 3, `ac_etime` is a 32-bit floating-point representation of elapsed **accounting ticks**, not seconds. `ac_utime` and `ac_stime` use 16-bit `comp_t`, with a 13-bit mantissa and 3-bit base-8 exponent. Decode the representation before converting units. Format 3 uses `AHZ=100` ticks per second; the cited older format branch uses the source platform's `USER_HZ`. Do not use the analyst host's clock setting or assume a float implies seconds. Keep raw values, version, endian, unit conversion and rounding with the termination record. METIS does not decode this binary format.
[Accounting frequency](https://github.com/torvalds/linux/blob/v6.12/include/linux/acct.h) and [writer](https://github.com/torvalds/linux/blob/v6.12/kernel/acct.c).

## Saved socket-state and task-creation observations

In saved `ss` output from iproute2 v6.18.0, `State` is rendered text: `SYN-SENT`
means the TCP endpoint is waiting after sending a connection request, while `ESTAB`
represents an established connection. Neither proves application success or an interactive
human session. Keep the displayed local/peer address and port, network namespace, host,
collection time and row coordinate together. A snapshot does not supply the handshake time;
process associations and column presence depend on the recorded output and collection rights.
Do not silently replace native `SYN-SENT` with an underscore alias used by another exporter.
[ss formatter](https://raw.githubusercontent.com/iproute2/iproute2/v6.18.0/misc/ss.c)
and [TCP state meanings](https://www.rfc-editor.org/rfc/rfc9293.txt).

For already acquired Linux trace data, locate the matching event definition under the
actual tracefs mount/instance, commonly
`/sys/kernel/tracing/events/sched/sched_process_fork/format`. Retain kernel build,
event ID, field type, byte offset and size from that acquired format; do not apply offsets
from a different build. Common trace-header fields are separate from event-specific fields.
[Event format contract](https://docs.kernel.org/6.12/trace/events.html).

In Linux v6.12, `sched_process_fork` defines `parent_comm` and `child_comm` as
`char[TASK_COMM_LEN]`, and `parent_pid` and `child_pid` as `pid_t` copied from each
kernel task's `pid`. These identify tasks, including threads, rather than guaranteeing
thread-group leaders. The text formatter labels the parent fields `comm` and `pid`;
those display labels are not replacements for the structured field names. A task-creation
event does not establish a later exec, network connection or malicious callback.
[Versioned event definition](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/trace/events/sched.h).

Scope task joins by host, boot, namespace mapping and lifetime because numeric IDs repeat.
Use acquired `saved_tgids` only when available to map thread IDs to TGIDs. Preserve the
selected `trace_clock` and the reader's timestamp units; trace timestamps have no universal
Unix epoch. The default `local` clock can differ across CPUs, while `counter` counts events
rather than elapsed time. Loss and disabled-event intervals remain coverage gaps. METIS does
not decode raw ftrace buffers.
[Trace clocks and TGID mappings](https://docs.kernel.org/6.12/trace/ftrace.html).

## Kernel and package logs depend on producer configuration

A kernel message may be acquired through `/dev/kmsg` or a retained journal. In systemd v255,
`_TRANSPORT=kernel` identifies journal entries received from the kernel; it is a transport
label, not a severity, process identity or proof of exploitation. Retain `MESSAGE`, the
journal locator and the machine/boot/time fields described above. Confirm collection and
retention before interpreting an absent message.
[Journal transport fields](https://github.com/systemd/systemd/blob/v255/man/systemd.journal-fields.xml)
and [journal input paths](https://github.com/systemd/systemd/blob/v255/man/systemd-journald.service.xml).

`/var/log/kern.log` is a conditional text-log candidate. Debian's rsyslog package configuration
8.24.0-1 routes the `kern.*` facility selector there and includes `/etc/rsyslog.d/*.conf`.
Resolve the acquired `/etc/rsyslog.conf`, included rules, enabled inputs and output template;
other distributions or revisions may choose different destinations or retain only a journal.
The cited configuration selects `RSYSLOG_TraditionalFileFormat`. Preserve the rendered time
and document any missing year/timezone; do not impose the journal's numeric clock contract
on a syslog text line. A journal entry and its forwarded text copy are not independent events.
[Versioned Debian logging configuration](https://sources.debian.org/src/rsyslog/8.24.0-1/debian/rsyslog.conf/).

On RHEL 7, `/var/log/yum.log` is the documented default package log; `[main]` `logfile` in
`/etc/yum.conf` can select another absolute filename. Preserve the acquired configuration,
log/member hash, line, rendered timestamp, package identity and stated transaction action.
Do not assume a universal timestamp column, epoch or timezone across package-manager versions.
[Versioned Yum configuration](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html-single/system_administrators_guide/index).

RHEL 8 has no direct equivalent with the same coverage. Its `/var/log/dnf.rpm.log` is a
candidate for retained package transactions, but the vendor documents that it excludes
PackageKit and microdnf transactions and is rotated. Compare retained transaction history
and the acquired package database with their own version/schema; a log's absence is not
proof that no package change occurred, and a package transaction is not application execution.
[Transaction-log differences](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/considerations_in_adopting_rhel_8/software-management_considerations-in-adopting-rhel-8).

## Journal filenames and configured storage populations

For systemd v255, `system.journal` is the active system-journal basename. In the
acquired default namespace, discovery candidates are
`/var/log/journal/{machine-id}/system.journal` and
`/run/log/journal/{machine-id}/system.journal`. Resolve the acquired machine ID,
namespace and effective configuration rather than requiring both files. In
`journald.conf`, `Storage=volatile` uses runtime storage; `persistent` prefers disk
but can fall back during early boot or when disk storage is unavailable; `auto`
depends on the persistent directory's presence. `none` disables journal storage
while configured forwarding can still occur. A later setting does not remove
older retained files or establish the configuration during an earlier interval.
[systemd v255 storage contract](https://github.com/systemd/systemd/blob/v255/man/journald.conf.xml)
and [basename selection](https://github.com/systemd/systemd/blob/v255/src/journal/journald-server.c).

Account for archived `system@{suffix}.journal` files and `.journal~` files; the
latter can result from an unclean stop or detected corruption. `SplitMode=uid`
can place regular users' messages in `user-{uid}.journal` under persistent
storage; volatile storage is not split this way. A service's `LogNamespace=` can
select a separate journal population, with persistent storage beneath
`/var/log/journal/{machine-id}.{namespace}/`. Default-namespace inspection alone
does not cover those records. Preserve the acquired file/hash and entry locator;
read time from the native entry fields above, not from a basename or filesystem
time. Missing files and parser failures remain coverage limits.
[Versioned file and namespace rules](https://github.com/systemd/systemd/blob/v255/man/systemd-journald.service.xml).

## Apport diagnostic-log location

For Apport 2.28.1, `/var/log/apport.log` is the default diagnostic destination
selected by `APPORT_LOG_FILE`. The crash-handler implementation redirects standard
output/error there when stderr is not a terminal and opening the selected log succeeds.
A terminal, an override or a failed open can therefore leave this file absent without
establishing that no diagnostic activity occurred. Resolve the acquired environment,
package version and file rotations; this is not a universal Linux crash-log location.

The handler's text format includes severity, the Apport process PID, formatted logging
time and message. The prefix PID belongs to the logger; distinguish it from a process
identified inside the message. Preserve the actual timestamp representation and host
clock context instead of imposing an epoch conversion or treating file modification
time as the crash time. These diagnostics are separate from a core dump or crash report;
a logged failure does not by itself prove exploitation or a complete crash population.
[Versioned destination and logger implementation](https://github.com/canonical/apport/blob/2.28.1/data/apport).

## Unverified package-state discovery name

`dnf.rbdb` is retained only as an unverified technical discovery name. Its producer,
version, storage location, file format, fields and clocks have not been established.
Do not automatically correct it to `dnf.rpm.log`, an RPM database or another known
package artifact. An acquired file with this name needs its own provenance, bytes and
schema validation; neither the suffix nor this listing establishes that it is a database.

## cloud-init raw user-data cache

For cloud-init 23.1.1 with its default state directory, `/var/lib/cloud/instance/user-data.txt` holds cached raw user-data. `instance` is a symlink to the active datasource instance directory under `/var/lib/cloud/instances/{path-safe-instance-id}/`; preserve the acquired link and its resolved target when correlating records. The `cloud_dir` setting can replace `/var/lib/cloud/`, and the implementation substitutes path separators in the instance identifier before forming the directory name. Verify the acquired configuration and datasource identity rather than joining records by the filename alone.

`user-data.txt.i` is the separate serialized processed MIME message. The raw-data writer substitutes empty bytes when no raw data is supplied, so an empty `user-data.txt` is not proof that a nonempty configuration was received. Neither file alone demonstrates that its contents ran or that initialization completed. User-data can contain secrets: keep content restricted and use independent logs or outcome evidence for execution and time claims.

Primary checks: cloud-init 23.1.1 [path mappings](https://github.com/canonical/cloud-init/blob/23.1.1/cloudinit/helpers.py) and [instance linkage and raw/processed storage](https://github.com/canonical/cloud-init/blob/23.1.1/cloudinit/stages.py). This is an offline locator contract for the pinned implementation, not a promise that every image retains these files or an additional built-in decoder.

## Alpine package transaction log

For apk-tools v3.0.0, a write-mode context with logfile output enabled opens
`var/log/apk.log` relative to its selected filesystem root; the default root is `/`.
Thus `/var/log/apk.log` is a discovery candidate for that default root, not an
application access log or an Android package file. Check the acquired root, release
and logging configuration before interpreting absence. This versioned contract does
not establish the layout or logging support of every earlier apk release.

The invocation header uses UTC from `gmtime_r` and renders `%Y-%m-%d %H:%M:%S` without
an explicit zone suffix. That header clock is distinct from a package build timestamp
and does not timestamp every following output line independently. Retain transaction
boundaries, package identity, action/result text and private line coordinates; package
activity does not prove application execution or completion of every requested change.
[apk-tools v3.0.0 root and logfile selection](https://github.com/alpinelinux/apk-tools/blob/v3.0.0/src/context.c),
[invocation clock writer](https://github.com/alpinelinux/apk-tools/blob/v3.0.0/src/print.c).
