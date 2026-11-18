# Happy Birthday

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily 2026-08 METIS evaluation |
| 問題番号 | happy-birthday |
| カテゴリ | Crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-17 02:02 JST） |
| Flag | - |
| タグ | crypto, sha256, truncated-hash, birthday-collision |
| 問題URL | https://alpacahack.com/daily/challenges/happy-birthday?month=2026-08 |
| METIS run | `1f8c26a2f7bd437e878297d37955fb0b` |

## 概要

Solved Happy Birthday with a cross-prefix collision against a truncated SHA-256 digest.

## 解析

The supplied checker decodes two hexadecimal inputs, requires distinct byte strings with exact user= and admin= prefixes, computes SHA-256 for each, truncates each digest to five bytes, and compares the truncated values. The equality check therefore exposes a practical 40-bit collision search while preserving the required distinct prefixes.

## 解法

Enumerate candidate suffixes for user= and admin= independently, index one side by its 40-bit digest, and search the other side for a match. Verify the pair against the stated predicates, then enter the pair as hex into the authorized challenge instance to obtain the challenge response. The official answer was submitted once through the AlpacaHack browser form and the UI displayed SOLVED!.

## 学び・再利用できる手法

For a truncated n-bit hash equality check, estimate generic birthday work from the output width before treating the full hash algorithm as collision resistant. Prefix constraints can be handled by generating independent candidate domains and matching their truncated digest outputs.


## 参考

- https://alpacahack.com/daily/challenges/happy-birthday?month=2026-08

## METISの記録

- 期間: 2026-11-17 01:53 JST 〜 2026-11-17 02:02 JST
- 使用アクション数: 12（official_flag_submission_browser ×1, read_only_artifact_analysis ×10, remote_service_stdio_bridge ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-17 02:02 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 378,110 | `de8db2c77bd02fa78e99f2fddaf8d50e7cb81921bb267a29ddc86705d8218be1` |
| 01-00-happy-birthday.tar.gz | 712 | `4d3b962e3455349a77efb99150497cf6c8288fdf480b89e0c942c5503a9b0ef6` |

### 接続先

- 34.170.146.252:32411

<sub>METIS writeup — 更新: 2026-11-17 02:03 JST</sub>
