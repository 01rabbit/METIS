# 具体的な所在・field の追加確認

この文書は基点commit `8f3f88c` 時点の監査記録です。その後の追加読解・修正・残存除去は[反復レビュー](review-cycles.md)を参照してください。

2026-09-29 時点で、追加候補 **808ファイルの指定範囲**について実読・除外の判断がそろいました。元資料全体の意味同値や「絶対に漏れがない」ことを示す結果ではありません。再利用可能な具体情報の欠落を補い、未確認の schema や時計は未確認のまま残しています。

| 母集団・作業 | 件数 | 確認の意味 |
| --- | ---: | --- |
| 元ファイル | 1,735 | 今回すべての内容 hash・サイズ・UTF-8 可読性を確認 |
| 非空 UTF-8 / 空ファイル | 1,502 / 233 | 文字コードの確認は意味の読解ではない |
| 以前の確認対象 | 151 | 重複排除後の過去の指定契約範囲。今回全件を読み直した意味ではない |
| 追加候補 | 808 | 上の151件とは重複せず、指定した読解・除外範囲が閉じた |
| 候補の初期確認 / 追加確認 | 21 / 787 | 初期は全文14・限定7。追加は検索 hit 上限を外して範囲を選択 |
| 以前の確認と候補の和集合 | 959 | 何らかの明示された読解範囲を持つファイル数 |
| 検索条件に当たらなかった非空テキスト | 543 | メタデータ・形状・静的検索のみ。意味未確認 |
| 反映済み batch / target 操作 | 10 / 35 | 同じ参照への追記を含む。parser 実装数ではない |

担当別の候補は初期21、親210、host161、data210、blindspots206です。親210は105・50・55件の receipt を結合しました。すべて元パス hash と内容 hash で照合し、808件に重複・欠落はありません。各資料の実際の行・文字範囲、JSON の限定 projection、同一文脈の再利用を [機械可読台帳](doublecheck-review.json) に記録しています。集約者が808件すべてを再読したとの意味ではありません。

行番号は1起点、文字範囲は0起点・終端を含まない Unicode 文字位置です。JSON projection は復号後の文字列内の位置で、raw 行の byte offset ではありません。表示上限や省略部分を全文確認へ繰り上げず、実在する終端へ座標を正規化しています。検索に当たらない本文や巨大なケース値の残部は読解済みと数えていません。

反映では、native field と collector の別名、型・単位・epoch、join のキーと範囲、観測から言える限界を補いました。各 batch の適用 receipt、旧版と現行版の hash、元資料の opaque hash は JSON に保持しています。詳細な事実単位の採否は [技術棚卸し](technical-retention.json) と各参照を併読してください。

| 参照群 | 今回補った主な契約 |
| --- | --- |
| [SIEM](../skills/soc-siem-hunt/references/wazuh-zeek-suricata.md) / [ECS](../skills/soc-siem-hunt/references/elastic.md) | 正確な selector、任意 field、証明書鍵長の bit と非圧縮 HTTP body の byte、alias の境界 |
| [CloudTrail](../skills/soc-cloud-identity-forensics/references/aws-cloudtrail.md) | KMS Sign/Verify の実 event field と API 名の差、message/signature がない場合の相関限界 |
| [Network](../skills/soc-network-forensics/references/packet-format-map.md) | BACnet・CAN・SIP/RTP・RDP、Modbus 応答の値欠落、MQTT の dollar-root 範囲 |
| [Browser / export](../skills/soc-browser-artifacts/references/history-downloads.md) | Firefox/Chromium の時計、拡張機能、FileZilla 設定、取得 schema の探索候補 |
| [Windows](../skills/soc-host-forensics/references/windows-artifacts.md) / [Linux](../skills/soc-host-forensics/references/linux-artifacts.md) / [Memory](../skills/soc-host-forensics/references/memory-analysis.md) | reconnect と session、7-Zip の REG_BINARY、WinSCP、LiME、会計 record の port 不在、symbol/cache の版条件 |
| [Telemetry](../skills/soc-detection-engineering/references/telemetry-windows.md) / [Application](../skills/soc-detection-engineering/references/telemetry-application-identity.md) | event ごとの GUID casing・型、Windows privilege/object、SQL、Tomcat の設定依存 locator |
| [Executable](../skills/soc-malware-triage/references/executable-field-map.md) / [Container](../skills/soc-triage/references/container-and-structured-fields.md) | ELF/SquashFS/PyInstaller、署名 hash の範囲、OCI layer/history、Intel HEX の record 意味 |
| [Document/mobile](../skills/soc-malware-triage/references/document-mobile-fields.md) / [Integrity](../skills/soc-triage/references/artifact-integrity.md) | BIFF/OLE/OOXML、Android/DEX/backup、7z header、版付き形式と integrity の限界 |

未確定候補は次の表と JSON に残しました。同じ候補が複数の担当表に現れるため、行数を独立した欠落件数として足し上げないでください。host の追加161件中16ファイル、blindspots の7候補群には未確定の契約が残っています。探索名を技能に保持したことは、型・時計・版・decoder の検証完了を意味しません。

| 未確定の候補 | 必要な確認・対応先 |
| --- | --- |
| A claimed Jump List AppID hash recipe needs independently verified algorithm parameters, input canonicalization and test vectors. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| ShellBag derived first/last-interaction labels depend on parser version, key association and MRU interpretation. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| MAM checksum variants need independent native evidence before assigning one universal CRC rule. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Per-user FileExts paths must be resolved to their actual user hive, not assumed to live under machine SOFTWARE. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Compatibility Assistant Store locator is plausible, but SACP size/count/date offsets are not universal. Selector: `Compatibility Assistant/Store`, `SACP`, `size/count/time candidate offsets`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| ShellBag node, view-bag and embedded DOS dates have different provenance. Selector: `BagMRU LastWrite`, `Bags LastWrite`, `embedded DOS dates`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| CLR private VAD/vtable/heap layout can be build-specific. Selector: `CLR Module/Assembly candidate layout`, `VAD/heap interpretation`. | [対応参照](../skills/soc-host-forensics/references/memory-analysis.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| OneDrive private database columns require schema/version and clock semantics. Selector: `od_ClientFile_Records.lastChange`, `diskCreationTime`, `eTag`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Desktop synchronization client DB names do not establish native schema, encryption or clocks. Selector: `desktop sync client database candidates`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| JFFS2 candidate layout/compression claims need exact version/CRC scope validation. Selector: `JFFS2 totlen/node header/CRC scope`, `raw LZMA candidate`. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Device-tree nvmem cells describe board-specific data layouts. Selector: `nvmem-cells candidate layout`. | [対応参照](../skills/soc-malware-triage/references/executable-field-map.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Legacy ZIP encryption check-byte selection is conditional on format flags. Selector: `general-purpose bit3`, `legacy encryption check-byte`. | [対応参照](../skills/ctf-crypto-solve/references/encrypted-evidence.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Volatile Environment session registry values can corroborate session context. Selector: `HKU SID/Volatile Environment/session`, `CLIENTNAME`, `SESSIONNAME`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| OAlerts channel and Event ID 300 are discovery candidates. OfficeOAlerts is a convenience label, not a verified native provider name; actual provider/version/payload types require acquired XML and matching schema. Selector: `OAlerts channel`, `Event ID 300`, `System/Provider/@Name`, `Version`, `EventData/Data`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Acquisition CopyLog can expose tool-specific source hash fields. Selector: `SourceFileSha1 candidate`, `ConsoleLog target list`. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| AD1 and application investigation databases can contain private layout candidates. Selector: `AD1 candidate offsets`, `private investigation SQLite schema`. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| AD1 layout: Empirical offsets lack a verified versioned specification. Do not promote fixed offsets; retain as unsupported-layout candidate. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| API Monitor / RBAPM layout: Empirical RBAPM/member offsets remain a candidate layout, already explicitly unsupported without version validation. | [対応参照](../skills/soc-malware-triage/references/api-monitor-candidate-layout.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| OneDrive database clocks: lastChange and diskCreationTime need schema/version validation; do not conflate remote creation with local materialization. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Saleae proprietary varint layout: No primary confirmation for the proposed proprietary varint layout; no custom decoder imported. | [対応参照](../skills/soc-network-forensics/references/packet-format-map.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| WhatsApp crypt14 layout: Case-derived crypt14 offsets and decryption behavior are not a universal schema; no password recovery or decoder port. | [対応参照](../skills/soc-malware-triage/references/document-mobile-fields.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| IMAGEWTY firmware container: IMAGEWTY-specific layout and embedded partition assumptions are not verified as general support; property and DEX facts are independently covered. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Android application and network databases: softap.conf, mmssms.db sms, contacts2.db and Play Store suggestions.db are candidate artifacts only; acquisition-relative roots, app/OS version and database schema are unresolved. No secrets, password recovery or proprietary layout promoted. | [対応参照](../skills/soc-malware-triage/references/document-mobile-fields.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Windows Search gather logs can be discovery candidates, but their native layout and clock need acquired-version verification. Selector: `SystemIndex.*.gthr`, `GatherLogs/SystemIndex`, `mapi URI`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| ActivitiesCache ActivityType/contentUri selectors require schema and data-location confirmation. Selector: `ActivitiesCache.db`, `ActivityType`, `contentUri`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Ntfs Operational145 exposes potential volume/device correlation selectors. Selector: `VolumeName`, `DeviceSerialNumber`, `DeviceSerialNumberLength`, `VolumeCorrelationId`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Registry CPU string selector is a discovery lead. Selector: `HARDWARE/DESCRIPTION/SYSTEM/CentralProcessor/0`, `ProcessorNameString`. | [対応参照](../skills/soc-host-forensics/references/windows-artifacts.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Generated cache leaf length may affect a platform-specific path budget. Selector: `data_ SHA512 .cache leaf`. | [対応参照](../skills/soc-host-forensics/references/memory-analysis.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Android application files/databases are discovery leads requiring exact acquisition/build schema. Selector: `/misc/wifi/softap.conf`, `mmssms.db/sms`, `contacts2.db`, `suggestions.db`. | [対応参照](../skills/soc-malware-triage/references/document-mobile-fields.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Flask session serialized format must be matched to serializer/version. Selector: `Flask session serialization`. | [対応参照](../skills/soc-malware-triage/references/executable-field-map.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| AD1/MANS private layout requires matching format/schema verification. Selector: `AD1 offsets`, `MANS table candidates`. | [対応参照](../skills/soc-triage/references/artifact-integrity.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Blockchain identifiers and operation history require the relevant chain/network native contract. Selector: `blockchain operation history`, `chain-specific address validation`. | [対応参照](../skills/ctf-crypto-solve/references/encrypted-evidence.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Unrecognized provider, sensor and browser builds | [対応参照](../skills/soc-siem-hunt/references/wazuh-zeek-suricata.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| For acquired forensic SQLite exports including MANS-related acquisitions, FileDownloadHistory.SourceURL, Files.ID/FileName and FileStrings.FileID remain existence/type/key-scope candidates. No universal join, clock conversion or parser support is asserted. | [対応参照](../skills/soc-browser-artifacts/references/history-downloads.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Private TCC table columns and numeric authorization/clock interpretation require an acquired OS-version schema; no numeric decoder is validated. | [対応参照](../skills/soc-detection-engineering/references/telemetry-specialist.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Collector-specific DNS authority summaries and undocumented protocol aliases or vendor byte offsets are not native schema contracts. Verify sensor/version and reassembled message boundaries. | [対応参照](../skills/soc-network-forensics/references/packet-format-map.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |
| Application-specific API/client schemas and detection-signature vocabulary are not general native evidence columns; unverified versions remain unsupported. | [対応参照](../skills/soc-siem-hunt/references/wazuh-zeek-suricata.md)。版・実 schema・型・意味を取得物と一次契約で検証するまで未確定。 |

追加知識は同梱 decoder の実装を増やしたものではありません。非対応の私有レイアウト、未知の build、symbols、外部 reader、collection coverage は別途必要です。MANS 系の `FileDownloadHistory.SourceURL`、`Files.ID` / `FileName`、`FileStrings.FileID`、CopyLog の `SourceFileSha1` / `ConsoleLog` も、存在を取得 schema で確かめる候補であり、普遍的な型・clock・join を与えていません。

今回 source 画像の描画と暗号化 artifact の復号は行っていません。非空ファイルが UTF-8 で読めても、内部の符号化媒体や暗号文を理解したことにはなりません。公開 regression は既知の設問での保持確認であり、未読543件や未知形式を含む一般性能・完全性の証明ではありません。元本文・コード・媒体・案件値・元パスはこの台帳へ保存していません。
