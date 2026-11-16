# fsbase modification

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | fsbase-modification |
| カテゴリ | pwn |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:02 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/fsbase-modif-fsbase-modification.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | pwn, canary, fsbase, ret2win |
| 問題URL | https://alpacahack.com/daily/challenges/fsbase-modification |
| METIS run | `984d10314a9346beb94f0abcbe36ff10` |

## 概要

arch_prctl(ARCH_SET_FS) でカナリア読取元(%fs:0x28)を .bss のゼロに向け、既知カナリア(0)で BOF -> ret2win。

## 解析

fsbase=0x404038-0x28=0x404010。win=0x4011b6。read(0,buf,32) で buf(8)+canary(8)+rbp(8)+ret(8)。

## 解法

入力1: 4210704。入力2: A*8 + \x00*8 + B*8 + p64(0x4011b6)。

## 使用したスクリプト

- [fsbase-exploit.txt](files/fsbase-modif/fsbase-exploit.txt)

## 学び・再利用できる手法

arch_prctl(ARCH_SET_FS) でカナリア読取元(%fs:0x28)を .bss のゼロに向け、既知カナリア(0)で BOF -> ret2win。

- **arch_prctl(ARCH_SET_FS) to relocate the stack-canary source**（pwn）: If the program lets you set the FS base (arch_prctl ARCH_SET_FS) before a canaried function runs, the canary read at %fs:0x28 comes from an attacker-chosen address. Point FS so that FS+0x28 falls on a qword whose value you know (e.g. a zero-initialised .bss slot in a no-PIE binary => canary 0). Then a stack overflow can overwrite the return address past a 'known' canary and ret2win.
  - 適用条件: User-controlled FS base via arch_prctl before a stack-protected vulnerable function, plus a stack buffer overflow and a win()/one-gadget.

## METISの記録

- 期間: 2026-11-13 20:34 JST 〜 2026-11-13 21:02 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, remote_service_exchange ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:02 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 377,105 | `aff50f49a574c5ad5d7973ada0bb862fef8cf705780ea4eb094a91c38881a87c` |
| 01-00-fsbase-modification.tar.gz | 3,944 | `cb865185744e9f0ee8fce7a89d3cb02da3be24ba923f409ee34d2899c714e599` |
| .metis-web/370848fead444dab902ba8785b74722d.gz | 3,944 | `cb865185744e9f0ee8fce7a89d3cb02da3be24ba923f409ee34d2899c714e599` |
| .metis-remote/607348d569eb4a0cae27c082ca55cf93.recv | 148 | `c42f9b7b9241e2bbd9e9853e8576954486526bfc29e497922a833ae6321447ff` |
| .metis-remote/36d871e090684e16a7bddb8df0018995.json | 516 | `4eda8b3ee5cd17fd9680943e985792490184d7d164fef45f07d362a2c736e4b0` |

### 接続先

- 34.170.146.252:26931

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
