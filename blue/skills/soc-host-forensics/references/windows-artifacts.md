# Windows evidence decision guide

## Event populations

Choose provider and event ID together. For each record retain host, channel, record number,
UTC SystemTime, principal, session/process key and the original named fields. Check audit
configuration and ingestion coverage before interpreting an empty query.

| Question | Starting events | Necessary qualification |
| --- | --- | --- |
| Authentication outcome | Security 4624 and 4625 | Read logon type, source, status and account; success is not a compromise verdict. |
| Session lifetime | 4624 with 4634/4647 | Correlate host and logon ID, allowing missing termination and reused IDs. |
| Explicit credentials or privileges | 4648 and 4672 | Administrative workflows are common; identify originating process and change context. |
| Execution | 4688 or Sysmon 1 | Command-line collection is configurable; PID alone is not a stable cross-host key. |
| Service changes | Security 4697 or System 7045 | A service installation needs lineage and purpose, not just a recognizable name. |
| Task lifecycle | 4698/4699/4702 and TaskScheduler records | Creation, modification and action execution are separate events. |
| Account/group change | 4720/4722/4724/4728/4732/4738 | Identify actor, target and actual value/membership change. |
| Kerberos/NTLM | 4768/4769/4771/4776 | RC4 tickets or absent Kerberos are leads; neither uniquely proves credential theft. |
| Share access | 5140/5145 | Differentiate connection, requested access and successful data operation. |
| Log clearing | Security 1102; applicable System provider 104 | Correlate maintenance, actor and collection continuity. |

Sysmon supplies process creation (1), network (3), image loading (7), remote thread creation
(8), process access (10), file creation (11), registry changes (12–14), alternate-stream
metadata (15) and DNS (22), when enabled. An access mask, private memory region or LSASS
target is insufficient alone for a malicious verdict. Registry change events are not read
auditing. Zone.Identifier can support an origin assessment but is not an execution record.

RDP uses several phases: transport/authentication, session creation, shell start and reconnect.
Correlate Security type 10 with the TerminalServices channels instead of treating 1149 alone
as proof of an interactive desktop. For PowerShell, distinguish 4103 from 4104 and account for
multipart script blocks. WMI subscriptions and task action records need their specific fields.

## Registry and execution artifacts

Work on a consistent hive-plus-transaction-log copy. Compare log sequence numbers rather
than assuming a filename determines recency. Keep input/output digests when replaying a
dirty hive. Resolve the active control set and account context before choosing a path.

Investigate service configuration, Run/RunOnce entries, Winlogon values, IFEO debugger
settings, file associations, per-user activity, device history and local accounts according
to the question. Presence of a configured mechanism does not establish that it executed.

| Artifact | Useful evidence | Boundary |
| --- | --- | --- |
| Prefetch | Internal execution times, run count and referenced files | Version-specific; does not independently identify a user. |
| Amcache / ShimCache | File and compatibility inventory | Inventory presence is not a universal execution proof. |
| UserAssist / BAM | User-scoped activity or recent execution signals | Coverage differs by launch mechanism and OS version. |
| SRUM | Application/resource accounting | Buckets and retention limit exact timing. |
| LNK / jump lists | Target, volume and application/user context | Existence can reflect shell activity without the asserted human action. |
| MFT / USN | File metadata and change records | Timestamp semantics, record reuse and journal wrap constrain reconstruction. |

Jump-list application identities can depend on a canonical shell identifier rather than a
literal executable path. Resolve Known Folder substitutions and explicit AppUserModelIDs;
compare architecture/version and independently known mappings before assigning an application.
Do not assume that two lists with identical destinations represent the same application.

Shellbag tools may derive “interaction” fields from a containing BagMRU key and MRU position,
rather than the selected folder's own last-write time. Inspect the parser's field definition,
parent/child relation and neighboring navigation records. Avoid promising an exact browse
time from an unexplained GUI label.

## Correlation and anti-forensics

For remote service, WMI, WinRM, RDP, task and share activity, collect both source and destination
evidence. Keep transport, authentication, process effect and file effect as separate stages.
A familiar administration tool is not automatically attacker activity.

Investigate unexpected gaps, shortened journals, changed auditing and timestamp divergence.
Normal copies, installers, retention and acquisition errors are alternatives to tampering.
No single timestamp or event code determines intent. Use
[parser checks](parser-integrity.md) for precision, malformed records and completeness.


## Evidence locations and native fields

以下の所在は一般的な初期値です。取得対象の OS、ユーザープロファイル、設定、収集一覧で実在を確認してください。環境変数は証拠ホスト側の値として解決します。METIS の同梱リーダーは UTF-8 Event XML のみで、ここに挙げる binary EVTX、Registry、ESE、Prefetch、LNK、NTFS の解析には別の検証済みツールが必要です。

| 調査対象 | 探す場所・入力 | 抽出して残す情報と限界 |
| --- | --- | --- |
| Windows イベント | `%SystemRoot%\System32\winevt\Logs` の対象チャネル、またはチャネル設定で指定したファイル | `System/Provider/@Name` と `@Guid`、`EventID`、`Version`、`Channel`、`Computer`、`EventRecordID`、`TimeCreated/@SystemTime`。レコード番号はチャネル/取得元と組にし、別ファイルの同番号を同一事件としない。 |
| システム hive | `%SystemRoot%\System32\config` の `SYSTEM`、`SOFTWARE`、`SAM`、`SECURITY` と対応ログ | `SYSTEM\Select` の `Current` 値から `ControlSetNNN` を選択する。オフライン hive にライブ環境の `CurrentControlSet` があると仮定しない。 |
| ユーザー hive | `%USERPROFILE%\NTUSER.DAT`、`%LOCALAPPDATA%\Microsoft\Windows\UsrClass.dat` と対応ログ | SID、プロファイル、キー、値名、値型、原バイト、LastWrite、replay の有無を分離する。キー更新時刻は個々の値の変更時刻を保証しない。 |
| Prefetch | `%SystemRoot%\Prefetch\*.pf` | 内部実行名、形式 version、run count、全ての有効な実行時刻スロット、参照ファイル/volume。`.pf` の更新時刻を実行時刻にしない。形式と圧縮への対応を確認する。 |
| Amcache | `%SystemRoot%\AppCompat\Programs\Amcache.hve` と対応ログ | スキーマを列挙して `Root\InventoryApplicationFile` 等の実在を確認。パス、`FileId`、`ProgramId`、ファイルサイズ、metadata の意味を parser version と結び付ける。ハッシュの対象範囲を確認するまで full-file SHA-1 と同一視しない。 |
| SRUM | `%SystemRoot%\System32\sru\SRUDB.dat` と同じ収集時点の ESE 関連ファイル、`SOFTWARE` hive | アプリ/ユーザー ID の解決とカウンターの集計区間を確認。ESE を SQLite として開かない。集計値から接続先や通信内容を復元できるとは限らない。 |
| 最近の項目 | `%APPDATA%\Microsoft\Windows\Recent` の LNK、同所の `AutomaticDestinations` と `CustomDestinations` | target path、volume serial、LinkInfo、target timestamps、DestList entry と AppID。shortcut 自身の時刻と target metadata を分離。ファイル本文を人が読んだ証拠とは限らない。 |
| Activities | `%LOCALAPPDATA%\ConnectedDevicesPlatform` 配下のプロファイル別 `ActivitiesCache.db` と存在する WAL/SHM | 実スキーマを確認して `Activity`、`ActivityOperation` の `Id`、`AppId`、`Payload`、`StartTime`、`EndTime`、`LastModifiedTime` を保存。アプリ由来の活動や同期記録をプロセスの生存期間へ置換しない。 |
| NTFS | 同じ volume の `$MFT`、`$Extend\$UsnJrnl:$J` | MFT record 番号と sequence、親参照、属性の種類を保持。USN の `FileReferenceNumber`、`ParentFileReferenceNumber`、`Usn`、`TimeStamp`、`Reason`、`FileName` を照合する。番号再利用と journal wrap を考慮する。 |
| RDP クライアント画像痕跡 | `%LOCALAPPDATA%\Microsoft\Terminal Server Client\Cache` の取得済み cache files | tile の原ファイル/offset、寸法、配置根拠、復元版、OCR crop を保存。画像片の並べ替えだけで画面全体・表示順・接続先・時刻を確定しない。 |

Hive の標準配置は [Microsoft Registry Hives](https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry-hives)、Prefetch と Amcache の収集場所は [Prefetch target](https://github.com/EricZimmerman/KapeFiles/blob/master/Targets/Windows/Prefetch.tkape) と [Amcache target](https://github.com/EricZimmerman/KapeFiles/blob/master/Targets/Windows/Amcache.tkape) を参照。場所は収集の出発点であり、存在や完全性の保証ではありません。

### Registry の読み取り対象

下表の hive はファイルとしての入力名です。相対キーと値名を別々に記録し、HKCU/HKLM の文字列だけでユーザーや hive を推測しないでください。32/64 bit registry view の違いも記録します。

| 入力 | キー/値 | 検証する内容 |
| --- | --- | --- |
| SYSTEM | `ControlSetNNN\Control\TimeZoneInformation`、`ControlSetNNN\Control\ComputerName\ComputerName` | 証拠ホストの設定。設定値だけで過去の夏時間や時計ずれを決めない。 |
| SYSTEM | `ControlSetNNN\Services` の各 service | `ImagePath`、`Start`、`Type`、`ObjectName`、存在すれば `Parameters\ServiceDll`。実行イメージ、サービス ID、実際の起動記録を照合。 |
| SYSTEM | `ControlSetNNN\Control\Session Manager\AppCompatCache` の `AppCompatCache` | OS/構造に合う reader で読む。存在や列挙を実行件数に変換しない。 |
| SOFTWARE / NTUSER.DAT | `Microsoft\Windows\CurrentVersion\Run` / `RunOnce`。NTUSER 側は先頭に `Software\` | キー、値名、設定された command を保存。設定の存在と実行を区別。 |
| SOFTWARE | `Microsoft\Windows NT\CurrentVersion\Winlogon`、`Microsoft\Windows NT\CurrentVersion\Image File Execution Options` | `Shell`、`Userinit`、各 executable キーの `Debugger` を必要な範囲で確認。正当な保守設定との比較を行う。 |
| NTUSER.DAT | `Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist` の GUID 別 `Count` | 値名は通常 ROT13。元の値名と復号後の名前を併記し、version に合う構造から run count/focus 関連値/時刻を読む。全ての起動経路を含む履歴ではない。 |
| NTUSER.DAT | `Software\Microsoft\Windows\CurrentVersion\Explorer` の `RecentDocs`、`RunMRU`、`TypedPaths`、`ComDlg32\OpenSavePidlMRU` | 選択・入力・ダイアログ操作の種類を区別。MRU 順序を絶対時刻へ変換しない。 |
| USRCLASS.DAT | `Local Settings\Software\Microsoft\Windows\Shell\BagMRU` と `Bags` | 親子キー、`MRUListEx`、`NodeSlot`、shell item と LastWrite を照合。GUI の interaction 列がどのキーに由来するか確認。 |
| SYSTEM | `ControlSetNNN\Services\bam\State\UserSettings` の SID 別値、旧 build では `bam\UserSettings` も確認 | アプリパスと時刻の解釈を OS build に結び付ける。BAM を一般的な process termination timestamp として優先しない。 |

Scheduled task は `%SystemRoot%\System32\Tasks` の定義と、SOFTWARE の `Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache` 配下を突き合わせます。`Tree` のタスク名と `Id`、`Tasks` の GUID と `Path` を照合してください。片側の欠落だけで隠蔽や実行不能と断定せず、取得時点・削除・破損・OS 差を調べます。XML では `Actions/Exec/Command`、`Arguments`、`WorkingDirectory` と `Principals/Principal/UserId`、`RunLevel` を別項目で読みます。[Task schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema)

### イベントを照合する具体的なフィールド

Security 行の provider は `Microsoft-Windows-Security-Auditing` です。以下は主に `EventData` の native 名であり、SIEM が変換した列名とは異なることがあります。同一レコードの provider、version、ID、時刻、値を一緒に保持します。

| レコード | 主な値と照合条件 |
| --- | --- |
| Security 4624 | `TargetUserSid`、`TargetUserName`、`TargetDomainName`、`TargetLogonId`、`LogonType`、`IpAddress`、`IpPort`、`WorkstationName`、`AuthenticationPackageName`。主体の `SubjectLogonId` と新規セッションの `TargetLogonId` を混同しない。 |
| Security 4625 | `Status` / `SubStatus`、対象アカウント、`LogonType`、`ProcessId` / `ProcessName`、接続元。`0xC000006A` はパスワード不一致、`0xC0000064` は未知ユーザー、`0xC0000234` はロック、`0xC0000072` は無効化。単独の失敗で悪意を判断しない。 |
| Security 4634 / 4647 | 4634 の `TargetLogonId`、4647 の `SubjectLogonId` を同じホスト・boot・期間のセッションへ結ぶ。終端欠落は終了不明。 |
| Security 4688 | `NewProcessId`、`NewProcessName`、`ProcessId`（作成元 PID）、`ParentProcessName`（対応 version）、`CommandLine`、`SubjectLogonId`。16進 PID と10進 PID を型付きで正規化し、生成時刻を含めて照合。 |
| Security 4689 / Sysmon 5 | 前者の `ProcessId`、`ProcessName`、`Status`、後者の `ProcessGuid`、`ProcessId`、`Image`、`UtcTime`。終了を直接記録する証拠を優先し、Prefetch/BAM/ファイル close から終了時刻を代用しない。 |
| Sysmon 1 / 3 / 11 / 22 | 作成の `ProcessGuid` / `ParentProcessGuid`、通信の `DestinationIp` / `DestinationPort`、ファイルの `TargetFilename`、DNS の `QueryName` / `QueryStatus` / `QueryResults`。host と GUID を結合し、PID 再利用を避ける。 |
| Security 4698 / 4702 / 4699 | `TaskName` と actor の `SubjectLogonId`。4698 の XML は `TaskContent`、4702 は `TaskContentNew`。4699 の削除記録に定義 XML があると仮定しない。 |
| Security 5145 | `SubjectLogonId`、`ShareName`、`ShareLocalPath`、`RelativeTargetName`、`AccessMask`、`AccessList`、`AccessReason`、`IpAddress`。要求/許可チェックとデータ転送の完了は別。 |
| PowerShell 4104 | `ScriptBlockId`、`MessageNumber`、`MessageTotal`、`ScriptBlockText`、`Path`。同一 host/script block の番号で再構成し、欠落・重複・衝突を報告。4103 の module logging と件数を合算して実行数にしない。 |
| RDP の複数チャネル | RemoteConnectionManager 1149、LocalSessionManager 21/22/24/25、Security 4624 type 10 を相関。user、送信元、session ID、各段階の時刻を保存。1149 だけで shell 起動まで確定しない。 |

`LogonType` は、2 が対話、3 がネットワーク、4 が batch による起動、5 が service によるログオン、7 が unlock による解除です。8 の `NetworkCleartext` は認証パッケージへの資格情報の渡し方、9 の `NewCredentials` は外向き接続用に別の資格情報を指定したセッションを表します。10 の `RemoteInteractive` はリモート対話型、11 の `CachedInteractive` はキャッシュした資格情報を使った対話型です。type 8 は資格情報を認証パッケージへ渡す形を表し、ネットワーク上でパスワードが平文だったとの証明ではありません。type 9 も認証の悪用を単独では証明しません。

Native fields: [4624](https://learn.microsoft.com/en-us/windows/security/threat-protection/auditing/event-4624)、[4625](https://learn.microsoft.com/en-us/windows/security/threat-protection/auditing/event-4625)、[4688](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4688)、[4689](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4689)、[Sysmon](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon)、[4698](https://learn.microsoft.com/en-us/windows/security/threat-protection/auditing/event-4698)、[4702](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4702)、[4699](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4699)、[5145](https://learn.microsoft.com/en-us/windows/security/threat-protection/auditing/event-5145)。

### SRUM と時間の型

SRUM network-data provider の table GUID は `{973F5D5C-1D90-4944-BE8E-24B94231A174}` です。実在する列を確認し、`AppId` / `UserId` を同じ DB の `SruDbIdMapTable.IdIndex` に結び、`IdType` と `IdBlob` の意味に応じて解決します。解決不能 ID を捨てずに残し、`BytesSent` / `BytesRecvd` は raw bytes で集計します。KB/KiB は表示時に明示します。`TimeStamp` と provider 固有の `ConnectStartTime` を一律に同じ時計として扱いません。[SRUM collection](https://github.com/EricZimmerman/KapeFiles/blob/master/Targets/Windows/SRUM.tkape)

次は `dissect.esedb` commit `ea5efb8a8fc2902e5e4d43f035b7461ffb9ef734` と `dissect.util` commit `2fbbb593b6b03e84adb35a8ca338e7ae20f9c4f4` の reader 解釈です。全 Windows 版の native schema を保証する表ではありません。

| Table と列 | この reader の時計・出力 | 保存型との区別 |
| --- | --- | --- |
| network-data `{973F5D5C-1D90-4944-BE8E-24B94231A174}` の `TimeStamp` | `oatimestamp` が OLE Automation の日単位として扱い、UTC `datetime` を返す。通常の非負値では 1899-12-30 起点、1 日は 86,400 秒 | helper は float 以外の整数を 64-bit IEEE 754 double のビット列として再解釈する。整数の大きさを Unix 秒として使わない |
| network-connectivity `{DD6636C4-8929-4683-974E-22C046A43763}` の `ConnectStartTime` | この table の型マップが `wintimestamp` を選択する。FILETIME は 1601-01-01 UTC 起点の 100 ns 単位で、reader 出力は UTC `datetime` | network-data の列であると推定せず、取得 table に実在することを確認する |

取得 ESE の column type、raw 値・bytes、table GUID と reader 版/hash を保存し、native 保存型と変換後の `datetime` 型を別に記録します。変換時の浮動小数点丸めや表示精度を原時刻の精度とみなしません。METIS 内蔵の SRUM decoder を意味する表ではありません。
[固定した SRUM reader](https://github.com/fox-it/dissect.esedb/blob/ea5efb8a8fc2902e5e4d43f035b7461ffb9ef734/dissect/esedb/tools/sru.py)、[固定した時刻変換](https://github.com/fox-it/dissect.util/blob/2fbbb593b6b03e84adb35a8ca338e7ae20f9c4f4/dissect/util/ts.py)

FILETIME は1601年1月1日 UTC からの100 ns単位で、Unix秒とは異なります。原整数と原 XML 時刻を残してください。Prefetch の形式17/23/26/30などでは構造が異なり、30内にも variant があります。新しい形式を旧形式の固定 offset で読むと誤った値が得られます。compressed MAM の展開、version、配列境界、有効スロット数を検証した reader を使い、未対応形式は解析不能と報告します。[File times](https://learn.microsoft.com/en-us/windows/win32/sysinfo/file-times)、[Prefetch format research](https://github.com/libyal/libscca/blob/main/documentation/Windows%20Prefetch%20File%20%28PF%29%20format.asciidoc)

## Registry selectors that need their backing hive

| Question | Native selector and value | Interpretation boundary |
| --- | --- | --- |
| USB mass-storage history | Offline SYSTEM: read `Select\Current`, then `ControlSetNNN\Enum\USBSTOR`; retain device-class and instance subkeys, optional `FriendlyName`/`ParentIdPrefix`, value types and key last-write | An instance name is not always a trustworthy hardware serial. Presence does not prove a particular file was copied; timestamp meanings require OS/version and property evidence |
| Explorer search history | User hive `Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery`; numbered values contain UTF-16LE search data; binary `MRUListEx` contains little-endian uint32 value IDs terminated by `0xffffffff` | Join the IDs to numbered values within the same key/hive. Key last-write is not a separate timestamp for every term; the layout is version-dependent |
| File-handler configuration | Resolve `HKCR\{ProgID}\shell\open\command` through machine `HKLM\Software\Classes` and user `HKCU\Software\Classes`; preserve the backing hive and default value type/data | HKCR is a merged view, and offline per-user classes may be in `UsrClass.dat`. A missing machine key does not exclude an overriding user entry |

[USB identifiers](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/identifiers-generated-by-usbstor-sys),
[USBSTOR reader](https://raw.githubusercontent.com/keydet89/RegRipper3.0/master/plugins/usbstor.pl),
[WordWheelQuery reader](https://raw.githubusercontent.com/keydet89/RegRipper3.0/master/plugins/wordwheelquery.pl)
and [HKCR merge rules](https://learn.microsoft.com/en-us/windows/win32/sysinfo/merged-view-of-hkey-classes-root)
provide distinct contracts; none assigns universal per-device/per-term activity times.

A browser handler such as `ChromeHTML\shell\open\command` can supply additional arguments.
Record any `--load-extension` directory from observed configuration or process command line,
then bind it to the actual extension manifest/member inventory and browser version. A registry
write, a launch argument, successful extension loading and subsequent network activity are
separate observations. Developer/test use is an alternative explanation; compare approved
configuration, actor and process lineage before labeling the change as persistence.

## Prefetch byte coordinates and version selection

On the decompressed SCCA stream, version is little-endian uint32 at `+0x00`, signature at `+0x04`,
reported stream length at `+0x0c`, executable name in the 60-byte UTF-16LE field at `+0x10`, and
header hash uint32 at `+0x4c`. The file-metrics offset uint32 at `+0x54` helps distinguish layouts.
These coordinates start at SCCA byte zero, not at an enclosing compressed wrapper.

| SCCA version/layout | Expected file-metrics start | FILETIME slot start/count | Run-count uint32 |
| --- | --- | --- | --- |
| 17 | `0x98` | `0x78` / 1 | `0x90` |
| 23 | `0xf0` | `0x80` / 1 | `0x98` |
| 26 | `0x130` | `0x80` / 8 | `0xd0` |
| 30, earlier layout | `0x130` | `0x80` / 8 | `0xd0` |
| 30, shifted layout | `0x128` | `0x80` / 8 | `0xc8` |

FILETIME slots are little-endian uint64, in 100 ns units since 1601-01-01 UTC. Preserve zero
slots as unused/unknown rather than asserting an execution in 1601. Validate header length,
section extents and layout together; do not choose a layout solely because one decoded date
looks plausible. Run count is the artifact's retained count, not a complete lifetime audit.
MAM-wrapped input needs a matching bounded decompressor; distinguish XPRESS-Huffman from other
XPRESS variants. Do not infer universal checksum semantics from a synthetic fixture, and do
not silently treat version 31 as version 30.
[Researched Prefetch layouts](https://raw.githubusercontent.com/libyal/libscca/main/documentation/Windows%20Prefetch%20File%20(PF)%20format.asciidoc)
are version-specific reverse-engineered descriptions, not a guarantee for every OS build.

## 再接続とアプリケーションの設定履歴

| 所在・版 | Native field / type | 意味と照合 |
| --- | --- | --- |
| Security の `Microsoft-Windows-Security-Auditing`、Event ID `4778`、Version `0` | `AccountName`, `AccountDomain`, `SessionName`, `ClientName`, `ClientAddress` は UnicodeString、`LogonID` は HexInt64。`System/TimeCreated/@SystemTime`, `EventRecordID`, `Computer` も保持 | 既存セッションへの再接続。RDP のほか Fast User Switching や Hyper-V Enhanced Session でも生じる。`LogonID` は同一ホスト・boot/session lifetime 内の 4624 と照合し、初回ログオンの件数へ足さない。console では `ClientName=Unknown`, `ClientAddress=LOCAL` があり、住所欄を常に IP として解析しない |
| ユーザー hive の `Software\Microsoft\Office\{version}\{application}\Security\Trusted Documents\TrustRecords`。Office 16.0 の Word/Excel/PowerPoint で報告された所在 | 文書を表す value name、native value type、binary bytes、キーの LastWrite、Office 版と Trust Center policy | 信頼状態の手掛かり。既存の文書パス表現を保持し、URI escaping や環境変数の展開は派生値として分ける。バイナリ内の時刻を信頼操作時刻と決めつけず、版対応の解析器が説明する clock を示す。マクロ実行・成功はプロセスやアプリケーションの別記録で確認する |
| 7-Zip 24.09 GUI の `HKCU\Software\7-Zip\Compression`、value `ArcHistory` | `REG_BINARY` に NUL 終端の UTF-16LE 文字列が連続する。元 bytes、文字列順序、キー LastWrite を保持 | 圧縮ダイアログが保持した archive path history。保存文字列自体に項目別時刻はない。キー更新時刻を各 archive の作成・圧縮完了時刻と同一視せず、実ファイル、USN とプロセス記録で確かめる。別版は保存形式を再確認 |
| WinSCP の registry storage は `HKCU\Software\Martin Prikryl\WinSCP 2` 配下の `Sessions` / `Configuration`。INI storage は実行ファイルと同名の `.ini` または `%APPDATA%\WinSCP.ini` が候補 | site の `HostName`, `UserName` は文字列、`PortNumber`, `FSProtocol` は整数設定として読む。実際の native registry type / INI section・key と製品版を保存 | `/ini` と session log の `Configuration`, `Local account` で使用 store と主体を解決。保存 site は接続や転送の成功を示さない。protocol の数値対応は版に合わせる。資格情報は値を展開せず保護された所在を参照する |

定義: [4778 schema](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4778)、
[Office TrustRecords の観測](https://isc.sans.edu/diary/Office%2Bmacro%2Bexecution%2Bevidence/27244)、
[Microsoft の trusted documents](https://support.microsoft.com/en-us/office/security-privacy/trusted-documents)、
[7-Zip 24.09 の設定](https://github.com/ip7z/7zip/blob/24.09/CPP/7zip/UI/Common/ZipRegistry.cpp)、
[文字列保存形式](https://github.com/ip7z/7zip/blob/24.09/CPP/Windows/Registry.cpp)、
[圧縮ダイアログ](https://github.com/ip7z/7zip/blob/24.09/CPP/7zip/UI/GUI/CompressDialog.cpp)、
[WinSCP storage](https://winscp.net/eng/docs/config) と [site fields](https://github.com/winscp/winscp/blob/master/source/core/SessionData.cpp)。

## 未検証の native 探索候補

この表は取得物内で所在・schema を探すためのリードであり、確認済みの decoder 契約ではない。
製品/OS build、provider/event version、実 hive/table/column、native type、単位・epoch・timezone、
更新契機と保持範囲を取得物と対応する仕様で確定するまで、固定 offset や時計変換を適用しない。
METIS の同梱 decoder がこれらを解析できるとの意味もない。値・資格情報は private case に保管する。

| 候補の所在・識別子 | 保持する selector と未確定の境界 |
| --- | --- |
| `Microsoft-Windows-Ntfs/Operational` の Event ID `145` | `VolumeName`, `DeviceSerialNumber`, `DeviceSerialNumberLength`, `VolumeCorrelationId` を実 XML/schema で確認する。型、長さの単位、正確な event 意味・発生条件は未検証。volume/device の照合候補であり、初回接続・本人性・コピー成功を単独で確定しない。 |
| Windows Search: `%ProgramData%\Microsoft\Search` 配下の `GatherLogs\SystemIndex\SystemIndex.*.gthr` という末尾を持つ取得物 | 完全 path と形式は使用版/設定から解決する。`mapi` 系 indexed URI は索引上の参照候補。binary record の field/type/clock は未検証で、整数断片を普遍的な FILETIME として復元しない。索引参照は元本文、メール到着、開封・実行の時刻を直接証明しない。 |
| `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store`。live HKCU の実ユーザー、offline の場合は対応する取得済みユーザー hive を特定する | value name の path と `REG_BINARY` 内の `SACP` 識別候補を保持する。サイズ・回数・時刻の固定 byte offset は版契約未検証のため使わない。 |
| OneDrive の `%LOCALAPPDATA%\Microsoft\OneDrive\settings` / `logs`。Personal account では `settings\Personal\SyncEngineDatabase.db` と対応 WAL が候補 | `od_ClientFile_Records` の `resourceID`, `lastChange`, `diskCreationTime`, `eTag`、`od_ServiceOperationHistory` と `EnumChanges` の存在を実 schema/row で確かめる。整数の幅・epoch、eTag の構造、operation 名の格納列は未検証。同期更新、cloud 上の作成、local materialization と同一視せず、同名 path だけで異なる resourceID や WAL 世代を結ばない。 |
| Dropbox の取得済み profile/sync root: `config.dbx`, `filecache.dbx`, `.dropbox.cache` | 使用版・account・設定で所在を解決する。DB 名から暗号化方式、table/column、時計、削除の意味を仮定しない。対応 reader がない内容は未評価にする。 |
| `HKU\{SID}\Volatile Environment\{session}` | `CLIENTNAME`, `SESSIONNAME` を取得時点の値/型と共に保持し、Sysmon 13 等があれば実 `TargetObject` と照合する。session component の意味と寿命は版依存。名前だけで遠隔接続、送信元IP、悪意を断定しない。 |
| Office alerts の `OAlerts` channel と Event ID `300` | 実 `System/Provider/@Name`, `Version`, `Channel` と `EventData/Data` の名前・順序・型を記録する。便宜上の OfficeOAlerts というラベルを native provider 名とみなさない。payload schema は未検証で、dialog 文面とクリック、macro/DDE の実行、成功を区別する。 |
| `ActivitiesCache.db` | `ActivityType` と `contentUri` の記述候補。実 column と `Payload` 内の key のどちらかを schema/record から区別する。数値 `5` の意味を普遍化せず、同期された活動・記述 URI とプロセス実行を分ける。 |
| `HKLM\HARDWARE\DESCRIPTION\SYSTEM\CentralProcessor\0` | `ProcessorNameString` を CPU 情報の照会先候補として保持する。実型/更新条件は未検証。文字列は物理個体の一意識別子やその key が実際に読まれた証拠ではない。 |
| ユーザーの `Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\OpenWithList` | actual user/hive、value name/type、記録順を確かめる候補。path の `Software` component と machine `SOFTWARE` hive を混同しない。履歴や関連付けだけで個別 file の実行を確定しない。 |

Prefetch の時刻 slot が未充填であっても、それ以前の未収集・無効化・削除/再生成を排除できない。
最古の残存 slot は保持された記録の最古であり、初回または生涯唯一の実行を保証しない。

この完全な PCA key の所在は [Microsoft KB5017811](https://support.microsoft.com/en-us/topic/kb5017811-manage-transport-layer-security-tls-1-0-and-1-1-after-default-behavior-change-on-september-20-2022-e95b1b47-9c7c-4d64-9baf-610604a64c3e) の対象 Windows 10 / Windows Server 2019 で確認できる。key の所在確認は binary payload の型・固定 offset・時計の検証を兼ねない。別 build では実 hive と対応仕様を確かめる。

## PowerShell version and channel qualify Event 4104

Windows PowerShell 5.1 uses `Microsoft-Windows-PowerShell/Operational` and provider GUID
`{A0C1853B-5C40-4B15-8766-3CF1C58F985A}`. PowerShell 7 on Windows uses
`PowerShellCore/Operational` and GUID `{f90714a8-5509-434a-bf6d-b1624c8a19a2}`.
Both can record Event ID `4104`; match the engine, provider and channel before comparing rows.
Keep that scope with host and `ScriptBlockId` when reconstructing numbered fragments.

Script-block logging describes processed script blocks under the applicable logging policy.
Check provider registration, effective logging, session timing and retained event coverage.
Protected Event Logging can encrypt sensitive event content using CMS. Thus an event is not
a guarantee of plaintext, complete deobfuscation, successful execution or the only surviving
trace of a memory-loaded component. An empty 4104 population alone establishes none of those
negatives. Keep process creation and module logging as separate observations.
[Windows PowerShell 5.1 logging](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_logging?view=powershell-5.1)
and [PowerShell 7 logging on Windows](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_logging_windows?view=powershell-7.5).


## Defender のローカル観測資料

取得済みコピーの実在一覧から以下を探します。所在は初期値・探索候補であり、
全buildに同じファイルや内部レコードが存在するとの保証ではありません。

| 所在・レコード群 | 保存する座標・値 | 判断の範囲 |
| --- | --- | --- |
| `%ProgramData%\Microsoft\Windows Defender\Support`。旧配置候補は `%ProgramData%\Microsoft\Microsoft AntiMalware\Support` | ファイル名、hash、取得時点、Defender platform/engine版。`MPLog-*`、`MPDetection*`、`MpWppTracing-*.bin` は実在確認する名前候補 | テキストlogとbinary traceを区別。`.bin`をEVTX readerへ渡したり、ASCII検索の陰性だけで記録なしとしない |
| 取得済み `MpSupportFiles.cab` | 元host、生成時点、CAB member名・hash、収集範囲。標準の保存先は上記の現行Support配下 | 同名packageが別hostにもある。含まれるtrace等を列挙し、package作成時刻を内包イベント時刻にしない |
| `Microsoft-Windows-Windows Defender/Operational`、provider `Microsoft-Windows-Windows Defender` | 1116は検出、1117は対処、1118は対処時の非重大エラー、5007は設定変更。共通Event XMLのhost・provider・version・record ID・SystemTimeと、各 `EventData/Data/@Name`・原値を保持 | 1116だけで実行や対処完了を断定しない。1117もhost全体の安全性を保証しない。5007の変更前後を保守記録や実際の設定と照合する |

Support配下の探索場所は[KAPEの取得対象](https://raw.githubusercontent.com/EricZimmerman/KapeFiles/master/Targets/Antivirus/WindowsDefender.tkape)、
packageの所在と内容は[Microsoftの診断資料](https://learn.microsoft.com/en-us/defender-endpoint/collect-diagnostic-data)、
IDの意味は[Microsoftのイベント一覧](https://learn.microsoft.com/en-us/defender-endpoint/troubleshoot-microsoft-defender-antivirus)に基づきます。
ここで扱うのは保持済みの資料です。新しいpackage生成はhostへの書き込みを伴うため、適用される許可を確認します。

内部traceから見つけた `pid`、`ProcessStart`、`TEL:`、`TelemetryOnly` などの文字列は、
確定schemaではなく調査の手掛かりとして扱います。ファイルhashとbyte範囲、encoding、
前後のrecord境界を残し、対応するbuildのdecode根拠が得られるまで型・epoch・状態値の意味を確定しません。
文字列の近接だけで同一processへ結合せず、PIDを使う場合はhost・boot・生成時刻の独立証拠を照合します。
ファイル名の時計や単独の内部状態値から除外設定、実行成功、妨害原因を決めません。
METISにこのbinary traceの検証済みdecoderはありません。
[Microsoftの解析範囲説明](https://jp-sec.github.io/blog/MDEClientAnalyzer-self-service-blog/)も内部診断fieldの公開範囲を限定しています。

## Amcache のアプリとファイルの結合

対応する形式の `Amcache.hve` では、`Root\InventoryApplicationFile` の `ProgramId` を、
同じ取得hiveの `Root\InventoryApplication` 配下で探索します。各subkey名と、存在する
`ProgramId` 値の両方を記録し、`ProgramInstanceId` を別IDとして保持します。
`Name`、`Publisher`、`Source` 等は一致したアプリ側recordの値として扱い、ファイル側metadataと混ぜません。
`0000ffff` のような末尾だけで結合先なしと決めず、実際のキー集合と値で照合します。
一致なしはそのhive・replay状態・schemaでの結果であり、host上にアプリがないとの証明ではありません。

参照した[Dissect readerの固定版](https://github.com/fox-it/dissect.target/blob/6431872425fb9302ed9b97988cd705929bb14f8e/dissect/target/plugins/os/windows/amcache.py)は、
両record群の `ProgramId` をstring出力として扱います。これはreader出力型であり、取得Registryの値型・原値は別に保存します。
`Root\File` / `Root\Programs` の旧形式に、新形式のnative名を無条件で適用しません。
結合しても実行やpublisherの信頼性が立証されるわけではありません。

## 旧 Google Drive client のローカル資料

Windows の旧 Google Drive / Backup and Sync の取得物では、対象ユーザーの
`%LOCALAPPDATA%\Google\Drive` と、その配下の `user_default` を探索候補にします。
KAPE の固定した収集定義はこの旧配置を `DriveFS` の配置と区別しています。
後継クライアントへ旧配置・schema をそのまま適用せず、取得した製品版、設定、実在一覧で解決します。
[収集定義](https://github.com/EricZimmerman/KapeFiles/blob/ed0f9c727fa65093ce0d1973c1ebac788860ff3a/Targets/Apps/GoogleDrive_Metadata.tkape)

保存済みコピーから `snapshot.db`、`sync_config.db`、`cloud_graph.db`、`sync_log.log`
と存在するsidecar・rotationを識別し、取得hashと実pathを残します。
`user_default` 配下を含む前二者とログの探索名は
[artifact定義](https://github.com/ForensicArtifacts/artifacts/blob/72726309f0cf8232d633c27e26dc1c0348709351/artifacts/data/cloud_services.yaml)
にあります。`cloud_graph.db` は
[固定したSQLECmd map](https://github.com/EricZimmerman/SQLECmd/blob/7f89270df81e4f2aadc191bbc3e223e6b42a8cad/SQLMap/Maps/Windows_GoogleDrive_CloudGraphDB.smap)
でも対象名として扱われます。これらは収集・reader側の定義であり、全製品版での存在保証ではありません。

名前だけでDB形式、table/column、保存型、clockや状態値の意味を確定しません。
取得schemaと対応readerを照合し、ログの時刻表現・timezone・record境界も別に確認します。
設定や索引の存在、cloud側metadata、local fileの存在、同期・転送の完了を区別してください。
一部のDBやログが見つかったことも、その不在も、単独では外部送信の成否を示しません。
METISがこれらの製品固有schemaをdecodeできるという意味ではありません。


## チャネル名とEVTXファイル名を分けて確認

既定配置の `%SystemRoot%\System32\winevt\Logs` では `Security.evtx`、`System.evtx`、
`Windows PowerShell.evtx` を探索候補にします。最後の名前は従来のWindows PowerShellログであり、
`Microsoft-Windows-PowerShell/Operational` と同じチャネルではありません。
exportされたコピーは任意の名前を持てるため、basenameだけでprovider/channelを決めず、内部の
`System/Channel`、`System/Provider/@Name`、event versionと取得元を再確認します。

許可されたライブ環境では読み取り用の `wevtutil gl System /f:xml` 等で実際のチャネル設定と
保存先を確認します。オフラインの従来ログ設定ではSYSTEM hiveの
`ControlSetNNN\Services\Eventlog` 配下の対象ログにある `File` 値が探索先になります。
この値の契約は `REG_SZ` または `REG_EXPAND_SZ` です。欠損時の初期配置と設定された配置を区別し、
取得OS側の環境変数とactive control setを使って解決します。原EVTXとexportコピーのpath/hashは別に保存します。
[Eventlog設定](https://learn.microsoft.com/en-us/windows/win32/eventlog/eventlog-key)、
[読み取りコマンド](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil)、
[PowerShellの保存ログ例](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.diagnostics/get-winevent?view=powershell-5.1#example-12-get-events-from-an-archived-event-log)。

## デバイス導入のSetupAPI記録

Windows Vista以降では `%SystemRoot%\inf\setupapi.dev.log` がデバイス/driver導入の探索先です。
Microsoftの形式記述ではANSI textなので、取得bytesと採用encodingを残し、UTF-8と決めつけません。
headerのOS/architecture、sectionのoperation title、存在するinstance identifier、前後の行範囲を保存します。
`>>>` のsection headerと `<<<` のfooterを組にし、`Section start` / `Section end` の時刻、
存在する `Exit Status` の16進statusを読むことで、単なる文字列出現と一つの導入処理を区別します。
時刻はlocal calendar timeでミリ秒3桁です。timezone/DST根拠を別に取り、文字列を無条件でUTCにしません。
instance identifierがPnP device instanceを示す場合は同じhostのdevice情報と照合し、
欠損したfooter/statusを成功として補完しません。導入記録だけで全USB接続回数、操作した人、
ファイル転送や機器の目的を確定せず、ログlevel・rotation・収集範囲も確認します。
[ログの所在とtext形式](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/setupapi-text-logs)、
[section headerとlocal clock](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/format-of-a-text-log-section-header)、
[section footer/status](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/format-of-a-text-log-section-footer)。

## Installer and guest-service log discovery

Microsoft's Edge support guidance identifies `%WINDIR%\Temp\msedge_installer.log`
for all-user installations and `%LOCALAPPDATA%\Temp\msedge_installer.log` for a
single user. Resolve variables in the acquired host/user context and retain installer
version, log hash and line boundaries. Installer activity, an update request and a
successful browser run are different observations.
[Microsoft's installation-log locations](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/manageability/update-install-rollback-failures).

For a clock comparison, Chromium 128.0.6613.84's timestamp-enabled Windows logger
uses `GetLocalTime` to write `MMDD/HHMMSS.mmm`: month/day and local time with three
fractional digits, without year or zone. This is a compatibility candidate for similar
Edge installer lines, not a verified format contract for every Edge build. Establish
the acquired producer's format, year, effective historical timezone and independent
same-event linkage before UTC conversion. Neither the filename nor today's timezone
setting supplies that missing context.
[Versioned Windows logging prefix](https://github.com/chromium/chromium/blob/128.0.6613.84/base/logging.cc).

For Windows guests with VMware Tools 13.0.x/13.1.x, the vendor documents
`C:\ProgramData\VMware\VMware VGAuth\logfile.txt.0`. Resolve the actual system-data
root, installed version and available rotations. This confirms a discovery location,
not a universal record schema, timestamp convention or rotation order.
[Vendor's version-scoped location](https://knowledge.broadcom.com/external/article/301481).

Under an acquired `ProgramData` tree, `VMware\RawdskCompatibility\vmrawdsk.log`
remains an unverified discovery candidate here. Producer/build, clock format and
retention must be established from the acquisition and corresponding implementation.
Do not assign it a universal local clock, assign the VGAuth file a universal UTC clock,
or join their startup-looking messages as the same boot without independent evidence.
