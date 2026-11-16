# Let's Shut Down Linux

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | lets-shut-down-linux |
| カテゴリ | misc |
| 配点 | 2.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:33 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/lets-shut-down-linux-let-s-shut-down-linux.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, syscall, reboot |
| 問題URL | https://alpacahack.com/daily/challenges/lets-shut-down-linux |
| METIS run | `9301d1821dea449c8c2b4c5222ee4bf6` |

## 概要

reboot(2) の magic 引数 0xfee1dead / 0x28121969 / LINUX_REBOOT_CMD_POWER_OFF(0x4321FEDC) を10進で渡すと UML が Power down して flag が出る。

## 解析

chal.c は arg1..arg3 を10進で読み SYS_reboot を呼ぶ。server.py は UML の出力に 'Power down' があり returncode==0 なら FLAG を表示する。reboot は magic1=0xfee1dead、magic2=0x28121969(他に 0x05121996 等)、cmd で動作を選ぶ。

## 解法

arg1=4276215469, arg2=672274793, arg3=1126301404 を順に送る。

```python
for v in ('4276215469','672274793','1126301404'): ...
```
`metis remote pipe` で送信し 'reboot: Power down' と flag を確認。

## 使用したスクリプト

- [lsdl-solver.py](files/lets-shut-do/lsdl-solver.py)

## 学び・再利用できる手法

システムコールの magic 値と cmd は man 2 reboot で確認する。

- **reboot syscall magic numbers**（misc）: reboot(2) は magic1/magic2 が正しく cmd=POWER_OFF のとき停止する。man 2 reboot の定数を10進で渡す
  - 適用条件: reboot システムコールの引数を指定させる問題

## METISの記録

- 期間: 2026-11-13 22:07 JST 〜 2026-11-13 22:33 JST
- 使用アクション数: 2（official_flag_submission_browser ×1, remote_service_solver_pipe ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:33 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 376,955 | `6c0a80056f4d16191a7a1d2d023195c44979a1909e855d2e52bc083c21f25178` |
| 01-00-lets-shut-down-linux.tar.gz | 4,369 | `6fe3d03b46455ca74b1510ea5409052782b23d33ea31beebd58641028cf23873` |
| .metis-remote/94a78e0532ec46118a8d573a44553284.recv | 3,313 | `14742e15199baa53d0ae1ef54ab9f2e618c4455e77e3b6cfdef7172867b11c4e` |

### 接続先

- 34.170.146.252:64817

<sub>METIS writeup — 更新: 2026-11-13 22:33 JST</sub>
