# クラッシュ・停止・緩和策の防御的な証拠座標

保存済み dump、ログ、build artifact を読み、クラッシュ発生・可用性への影響・侵害の有無を
別々に評価する。未知入力を生成して障害を再現したり、payload、offset 攻略、回避を実装しない。
時刻、host、boot/container、process start、PID/TID、binary hash と build ID を結合キーに含める。

| 証拠 | 保存する所在・field | 判断の限界 |
| --- | --- | --- |
| Windows minidump | `MINIDUMP_EXCEPTION_STREAM.ThreadId`, `ExceptionRecord`, `ThreadContext`; `MINIDUMP_EXCEPTION.ExceptionCode`, `ExceptionFlags`, `ExceptionAddress`, `NumberParameters`, `ExceptionInformation` | `ThreadContext` の descriptor は dump 内 RVA/size。`ExceptionAddress` は process VA。例外種別ごとの parameter 意味を確認し、全 exception に同じ read/write/execute 解釈を使わない |
| Module と命令 | dump の module `BaseOfImage`, `SizeOfImage`, `TimeDateStamp`, `CheckSum`、CodeView/PDB identity、対象 address の module-relative offset | 同名 DLL や同一 timestamp だけで一致としない。symbol の build と architecture を合わせる。stack unwind が壊れていれば最後の frame を原因箇所と断定しない |
| ELF core | `e_type=ET_CORE`, `PT_NOTE` の note owner/type、`NT_PRSTATUS`, `NT_PRPSINFO`, `NT_SIGINFO`, `NT_AUXV`, `NT_FILE` など存在する note、`PT_LOAD` の範囲 | register layout と note 内容は OS/ABI に依存する。`NT_FILE` の対応 range/path と build identity を確認する。core にない memory page はゼロだったとはいえない |
| Linux journal / coredump | `_MACHINE_ID`, `_BOOT_ID`, `__REALTIME_TIMESTAMP`, `_SYSTEMD_UNIT`; `COREDUMP_PID`, `COREDUMP_SIGNAL`, `COREDUMP_EXE`, `COREDUMP_COMM`, `COREDUMP_TIMESTAMP` | `COREDUMP_TIMESTAMP` は microseconds since Unix epoch。journal の収録時刻と crash 時刻を分け、core 本体の有無を確認する。保存ポリシーや resource limit により core がない場合がある |
| 監査と stderr | audit `ANOM_ABEND` の `pid`, `comm`, `exe`, `sig` と event timestamp/serial、同時刻の service stderr、kernel fault log | allocator の abort、segfault、`SIGABRT`/`SIGSEGV` は異常終了の証拠。通常バグ、入力破損、resource exhaustion も原因になり、頻度だけで攻撃者や成功を帰属しない |
| Hang / timeout | watchdog・service latency・queue depth、process state、記録済み stack、consumer の終了確認 | 応答 timeout は crash でも拒否応答でもない。未送信、送信済み応答不明、明示失敗、完了を分け、別 consumer が動いているのに枠を開放しない |

[Exception stream](https://learn.microsoft.com/en-us/windows/win32/api/minidumpapiset/ns-minidumpapiset-minidump_exception_stream)
と [exception fields](https://learn.microsoft.com/en-us/windows/win32/api/minidumpapiset/ns-minidumpapiset-minidump_exception)
で dump の native fields を確認する。[systemd-coredump の一次資料](https://github.com/systemd/systemd/blob/main/man/systemd-coredump.xml)
で crash timestamp と収集版を確認する。Linux の保存先や収集設定は
[host forensic guidance](../../soc-host-forensics/references/linux-artifacts.md) と取得環境の systemd/ABI に従う。

## 静的緩和策と実行時状態を区別する

PE では `DllCharacteristics` の `DYNAMIC_BASE`, `NX_COMPAT`, `GUARD_CF` と load-config の内容を
記録する。ELF では `PT_GNU_STACK.p_flags`, `PT_GNU_RELRO`, `DT_BIND_NOW`/関連 flags を確認する。
PIE・stack protector・CFI/CET は対応する metadata/code/build 設定と実行環境の両方を確認する。
import 1 個の有無、`ET_DYN`、緩和策を表す文字列だけで有効・無効を決めない。
[静的形式のフィールド表](../../soc-malware-triage/references/executable-field-map.md) へ戻って座標を検証する。

## 成功した影響を確認する

クラッシュ検知だけでは、クラッシュを伴わない不正動作を評価できない。process ancestry に加え、
同じ process lifetime 内の image/identity の変化、権限状態、file access、network operation を
監査・EDR・application 側から関連付ける。PID は再利用されるので boot と start time を含める。
service の正当な shell 起動や updater もあるため、承認された baseline と比べる。
process child がないという理由だけで、不正な読み取りや書き込みがなかったとはしない。

結論は crash/hang の事実、影響した期間・資産、原因候補、侵害を支持/反証する証拠、未収集範囲に分ける。
修正確認は通常入力と保存済み crash の読み直し、既存の安全な regression、設定確認で行い、
再発がない期間と収集 coverage を明示する。危険な異常入力を再配信する検証はこの技能の範囲外。
