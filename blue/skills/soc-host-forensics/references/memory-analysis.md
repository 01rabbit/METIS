# Memory investigation workflow

## Establish a usable image

Memory collection changes a live system and requires the relevant authority. Choose a method
appropriate to the OS/hypervisor and record its effects; a snapshot is not guaranteed atomic
across every memory, disk and network state. Preserve acquisition metadata and image digest.

Identify architecture, image/container format and kernel build. Verify symbol compatibility
before interpreting plugins. Windows symbol resolution and Linux kernel-specific type data
have different requirements. Prefer an approved local cache; a download is a separate action.

A layer-detection failure may be a parser limitation rather than damaged evidence. In
particular, architecture-specific page-table assumptions can invalidate a valid image.
Reproduce the parser error, confirm structure independently and use a supported version or
documented repair. Do not apply an old version's threshold patch indiscriminately.

## Select plugins by question

Read the installed tool's help: plugin names and availability change. METIS does not bundle
Volatility or its symbols.

| Stage | Typical views | Decision |
| --- | --- | --- |
| OS context | info, banners, layer/symbol diagnostics | Is the image interpretable by this tool/version? |
| Processes | list, pool scan, tree | Does disagreement reflect terminated, hidden or malformed structures? |
| Activity | command line, loaded modules, handles, SIDs | Which account, files and modules are associated with a process? |
| Network | socket/connection scans | Which endpoints are observed, with what lifetime uncertainty? |
| Suspicious regions | injection and module-consistency heuristics | Are JIT, security tooling and normal loader behavior excluded? |
| Persistence | registry, services, mapped files | Is the configuration supported by additional evidence? |

Executable private pages or a missing loader-list entry are triage signals. Confirm memory
permissions, mapping, provenance, bytes and process context before claiming injection.
Process names and expected ancestry are useful baselines but can be spoofed or version-specific.

On Linux, choose process/socket/file and kernel-module views appropriate to the kernel and
available symbols. Shell fragments recovered from memory may survive file deletion, but a
fragment alone does not prove execution. Bound strings searches and preserve offsets.

## Validate a result

Examine diagnostics as well as exit status. A plugin can return an empty collection after
failing to resolve symbols. Record scanned coverage, limits and unsupported structures.
Compare precise source plugins before using a merged timeline; repeated rows from the same
underlying object are not independent confirmation.

Extract suspicious regions only to private evidence storage for static analysis. Avoid
unnecessary credential extraction, and never publish credentials found in memory.
Complete with a process/event hypothesis, supporting object coordinates, alternatives and
specific missing evidence. Use [parser integrity](parser-integrity.md) for resource bounds.

## Name the image, layer and native output coordinate

Use [evidence locators](../../soc-triage/references/evidence-locators.md) for input/export hashes.
For a Windows image retain OS/build/architecture, identified kernel layer, DTB interpretation,
and the symbol table/PDB identity actually selected. For Linux, retain kernel banner/release,
architecture and exact distribution debug-kernel identity plus the produced ISF digest.
A matching release string alone does not prove that structures match. Preserve plugin/version,
renderer, arguments, stderr, status, limits and the row selector with every exported result.
METIS does not ship Volatility, acquisition software or a binary memory reader.

The following labels were checked against Volatility 3 documentation in the 2.28 series.
They are native plugin columns, not a schema METIS synthesizes. Inspect the installed plugin's
full name and output headers before using them; plugin versions and OS support can differ.
An abbreviated CLI plugin label is a discovery hint, never proof that a particular plugin ran.

| Question and plugin family | Concrete output fields to retain | Join and meaning limit |
| --- | --- | --- |
| Windows process inventory, `windows.pslist` with scan/tree counterparts | `PID`, `PPID`, `ImageFileName`, `Offset(V)` or `Offset(P)`, `Threads`, `Handles`, `SessionId`, `Wow64`, `CreateTime`, `ExitTime` | Bind PID and process-object address to image/layer and creation interval. The physical option changes the offset domain; do not use a kernel VA as a raw-file offset. A scan-only object can be terminated or damaged, not necessarily hidden |
| Windows connection objects, `windows.netscan` | `Offset`, `Proto`, `LocalAddr`, `LocalPort`, `ForeignAddr`, `ForeignPort`, `State`, `PID`, `Owner`, `Created` | Correlate image/process instance and time. Listener/UDP placeholders are not contacted peers. A recovered object does not prove a connection remained active at acquisition or transferred any bytes |
| Windows command/module/handle questions | Confirm the actual `windows.cmdline`, `windows.dlllist`, `windows.handles` or corresponding installed module; keep PID, object/address, exact rendered column and row | Command text, a module list entry and an open handle answer different questions. Missing or paged-out data remains unavailable; do not replace it with an empty string |
| Registry/service/file discovery in Windows memory | Identify the chosen `windows.registry.hivelist`, `windows.registry.printkey`, `windows.svcscan`, `windows.filescan` output; record hive/object offset, key/value or full file-object path and selected row | Configuration does not prove execution; a file object does not imply its entire content is resident. A key relative to one hive is not a globally unique registry path |
| Linux task list, `linux.pslist` | `OFFSET (V)`, `PID`, `TID`, `PPID`, `COMM`, `UID`, `GID`, `EUID`, `EGID`, `CREATION TIME` | Preserve process versus thread identity and namespace scope. Join by image/task address and lifetime rather than PID alone; a thread-inclusive count is not a process count |
| Linux shell-history recovery, `linux.bash` | `PID`, `Process`, `CommandTime`, `Command` | Values come from recognized history structures. Recovered text is not a complete execution audit; history time can be missing or manipulated, and memory residue can outlive activity |
| Linux descriptor view, `linux.lsof` | `PID`, `TID`, `Process`, `FD`, `Path`, `Device`, `Inode`, `Type`, `Mode`, `Changed`, `Modified`, `Accessed`, `Size` | Qualify an inode with device and image, and FD with process/thread. File metadata timestamps are not the time that descriptor was opened. Size is a byte count, not recovered-byte coverage |
| Linux sockets, `linux.sockstat` | `NetNS`, `Process Name`, `PID`, `TID`, `FD`, `Sock Offset`, `Family`, `Type`, `Proto`, `Source Addr`, `Source Port`, `Destination Addr`, `Destination Port`, `State` | Keep the namespace ID and socket address. One socket may be referenced by multiple tasks/descriptors; count rows separately from unique socket objects. A kernel socket view is not packet evidence |
| Linux page cache, `linux.pagecache.Files` | `SuperblockAddr`, `MountPoint`, `Device`, `InodeNum`, `InodeAddr`, `FilePath`, `InodeSize`, `InodePages`, `CachedPages` | `InodeSize` is bytes; the page columns are counts. A cache inventory does not establish complete file content. Keep inode address distinct from inode number; both need image/filesystem context |
| Targeted cached pages, `linux.pagecache.InodePages` when available | `PageVAddr`, `PagePAddr`, `MappingAddr`, `Index`, `DumpSafe`, `Flags`, `Output File` | `--inode` selects an inode address, not `InodeNum`; a supplied `--find` path is a selector. Dumping is a separate action. Preserve holes and errors; an emitted file is not automatically a complete original |

Definitions: [Windows processes](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/windows/pslist.html),
[Windows sockets](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/windows/netscan.html),
[Linux processes](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/linux/pslist.html),
[shell history](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/linux/bash.html),
[open files](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/linux/lsof.html),
[sockets](https://volatility3.readthedocs.io/en/latest/_modules/volatility3/plugins/linux/sockstat.html),
[page cache](https://volatility3.readthedocs.io/en/stable/_modules/volatility3/plugins/linux/pagecache.html)
and [Linux symbol preparation](https://volatility3.readthedocs.io/en/stable/getting-started-linux-tutorial.html).

## Reproduce the observation without overstating the snapshot

A raw-file byte offset, physical address, kernel virtual address and process virtual address
are different coordinates. Preserve the layer mapping and mapped span used for conversion;
segmented images and acquisition containers can break a direct physical-address/file-offset
assumption. Keep pointer width and endianness with any independently inspected structure.
For formatted times retain both the rendered UTC value and the available original field and
conversion precision; datetime rendering can discard sub-microsecond information.

Compare process-list/scan, loader/mapping and network views within the same capture. An
executable private region or an absent loader-list entry is a discrepancy to investigate, not
an injection verdict. Preserve region start/end, protection, mapped file, bytes and source
process when available; evaluate JITs, security software, termination and capture smear.
A string requires a bounded byte offset and owning layer/process/region before attribution.
Do not extract or publish reusable credentials to establish exposure.

Plan the smallest plugin set that answers the question. Record unavailable symbols and
unsupported architecture as failures. An exit code of zero with empty rows is not a negative
if stderr reports unsatisfied requirements. Apply aggregate I/O, elapsed time, memory and
output budgets; a per-file cap alone does not bound repeated reads. Keep each run in a fresh
private output directory, and keep generated reports outside the original evidence tree.
Symbols obtained with approved network access need recorded origin, digest and a reproducible
offline rerun before stronger replay claims. Never lower a structural-validation threshold
merely to force an image through a parser; retain the defect/version evidence and use a
supported fix. No model of acquisition makes every memory/disk/network observation atomic.

## Preserve the renderer's tree and timeline fields

Volatility 3 2.28 JSON output represents child rows under `__children`; JSONL can still carry
nested children within each root record. Walk supported row nodes while retaining the root
record/line and tree path, exact plugin, column names and rendered types. CSV uses `TreeDepth`
to express hierarchy. Arbitrary nested metadata is not another plugin row, and renderer
nesting does not by itself establish process ancestry: use the plugin's `PID`/`PPID` and object
semantics for that claim. Preserve JSON null, missing column, empty string and zero distinctly
where the format permits. The renderer can collapse different unavailable-value classes to
null; it cannot restore their original reason.
[Volatility 3 renderer](https://raw.githubusercontent.com/volatilityfoundation/volatility3/v2.28.0/volatility3/cli/text_renderer.py)

The `timeliner` columns are `Plugin`, `Description`, `Created Date`, `Modified Date`,
`Accessed Date`, and `Changed Date`. Keep each non-null date's column name and source row;
do not force these different event meanings into a single creation time or count one row as
one event. Date output follows the renderer; retain the raw representation, timezone/precision
and any unavailable value. Join repeated observations only with the underlying plugin/object
identity and capture, not matching description text. Plugin failure can leave an incomplete
aggregate timeline even when other plugins returned rows.
[Volatility 3 timeliner](https://raw.githubusercontent.com/volatilityfoundation/volatility3/v2.28.0/volatility3/framework/plugins/timeliner.py)

## LiME の区間と収集空白

LiME format version 1 は各メモリ区間に 32-byte packed header を置く。
header 相対 `+0` の `magic` と `+4` の `version` は 32-bit、`+8` の `s_addr` と
`+16` の `e_addr` は 64-bit、`+24` は 8-byte `reserved`。magic は `0x4C694D45`。
確認した writer は整数を native byte order のまま記録するため、取得ホストの endian を確認する。
`e_addr` は区間の最終アドレスを含み、payload の予定長は `e_addr - s_addr + 1`。
各 header のファイル座標、物理範囲、実在 payload 長を検証してからアドレスを写像する。

`raw` は物理アドレス間の穴を省き、`padded` は穴を埋め、`lime` は区間 header を持つ。
形式や圧縮 wrapper を確定せずに file offset を物理アドレスとして使わない。
取得版とログによっては無効ページ、読み取り失敗、timeout でゼロ埋めされた領域がある。
ゼロ列を「実メモリが空」と断定せず、未取得・補填範囲を coverage に残す。
[header](https://github.com/504ensicsLabs/LiME/blob/master/src/lime.h) と
[writer の区間・padding](https://github.com/504ensicsLabs/LiME/blob/master/src/main.c) を版照合に使う。

プロセス列挙の一致を評価するときは、plugin 名だけで独立した観測と数えない。
使用した symbol、走査元の list/hash table、memory layer と読み取り失敗を記録する。
二つの kernel memory view が一致しても、ユーザー空間の `/proc` 列挙が同じ内容を返した
ことや、別の取得時点に隠蔽がなかったことまでは証明しない。

## Symbol search paths and writable caches

Volatility 3 v2.28.0 splits `--symbol-dirs` on semicolons on every operating system.
Treat each component as a distinct directory, and reject an ambiguous literal semicolon in a
single directory name when preparing the argument. `--cache-path` selects the cache directory;
it is not an alias for the symbol search path. Record both resolved paths and the actual symbol
identity used by the plugin. Keep case-specific writable caches separate from inventoried
runtime/symbol inputs, and retain dependency failures even when stdout is valid JSON or the
process exits successfully. An offline option does not replace an environmental network policy.
[Versioned CLI definitions](https://github.com/volatilityfoundation/volatility3/blob/v2.28.0/volatility3/cli/__init__.py).

## Native OS-context rows in Volatility 3

In Volatility 3 v2.28.0, `windows.info` emits `Variable` and `Value`, both declared as
strings. Preserve the label and rendered value together with image, layer and plugin version.
Do not infer a numeric or datetime column type from its appearance.

| Native labels | Origin and boundary |
| --- | --- |
| `Kernel Base`, `DTB`, `Symbols`, `Is64Bit`, `IsPAE` | The first two render hexadecimal layer-configuration offsets; `Symbols` names the selected ISF location. Boolean results are also rendered as strings. Retain the layer's address interpretation and actual symbol digest; a plausible address does not validate symbols. |
| `Major/Minor`, `NtMajorVersion`, `NtMinorVersion`, `NTBuildLab`, `CSDVersion` | `Major/Minor` comes from the debugger version structure, while `NtMajorVersion` and `NtMinorVersion` come from shared kernel data. The build/service-pack rows depend on the KDBG signature check. Keep these distinct; combining display values into a legacy profile name does not establish compatible type information. |
| `SystemTime`, `PE TimeDateStamp` | The former reflects shared kernel time; the latter renders the kernel PE header timestamp through a UTC conversion. Neither establishes acquisition start, boot time or a trustworthy compilation time. Preserve their different origins and rendered precision. |

[Versioned Windows info implementation](https://raw.githubusercontent.com/volatilityfoundation/volatility3/v2.28.0/volatility3/framework/plugins/windows/info.py).
