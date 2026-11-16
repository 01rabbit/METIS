# x32 ABI flag checker

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | x32-abi-flag-checker |
| カテゴリ | rev |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:39 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/x32-abi-flag-x32-abi-flag-checker.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, x32, md5 |
| 問題URL | https://alpacahack.com/daily/challenges/x32-abi-flag-checker |
| METIS run | `72b68f9f2ef24ed68a339eefc0b6b09c` |

## 概要

隣接バイト対ごとの MD5 を 40 要素のテーブルと比較。各要素を 65536 通り総当たりで一意復元。

## 解析

check@0x40196f: strlen-1==0x28、各 (s[i],s[i+1]) を変換し MD5、table@0x4c40e0[i] と memcmp。

## 解法

各テーブル要素に対し全バイト対を総当たり、一意解が連鎖してフラグを構成（静的、バイナリ未実行）。

## 使用したスクリプト

- [x32-solve.py](files/x32-abi-flag/x32-solve.py)

## 学び・再利用できる手法

隣接バイト対ごとの MD5 を 40 要素のテーブルと比較。各要素を 65536 通り総当たりで一意復元。

- **Invert a per-pair MD5 flag checker by brute force**（rev）: If each flag byte-pair is hashed (MD5 of a small transform) and compared to a table, brute-force all 65536 pairs for each table entry; a unique match per entry that chains consistently reconstructs the flag.
  - 適用条件: A checker that hashes small (<=16-bit) chunks of the input against a fixed table.

## METISの記録

- 期間: 2026-11-13 20:31 JST 〜 2026-11-13 20:39 JST
- 使用アクション数: 2（official_flag_submission_browser ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:39 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 373,264 | `c1aa00a3e29195f00ae7e39c552b238cc60f50d46c01f5ec8d14e5bdfd5b9152` |
| 01-00-x32-abi-flag-checker | 873,848 | `1dea123810940b876652cf778b6611f149f5839ac6e63d0cb094cc2dfccb4fee` |
| .metis-web/80ba18941c454d6281abe9a743b56ba4.bin | 873,848 | `1dea123810940b876652cf778b6611f149f5839ac6e63d0cb094cc2dfccb4fee` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
