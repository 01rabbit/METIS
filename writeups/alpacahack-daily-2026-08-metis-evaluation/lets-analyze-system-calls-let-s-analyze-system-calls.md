# Let's analyze system calls

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily 2026-08 METIS evaluation |
| 問題番号 | lets-analyze-system-calls |
| カテゴリ | Rev |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-17 01:23 JST） |
| Flag | - |
| タグ | reverse-engineering, syscalls, alpacahack |
| 問題URL | https://alpacahack.com/daily/challenges/lets-analyze-system-calls?month=2026-08 |
| METIS run | `1709125dc8f645f4a7c72a86efa1d210` |

## 概要

Solved an authorized AlpacaHack Daily reverse-engineering challenge through static source analysis and the official browser submission flow.

## 解析

The supplied archive was gzip-compressed. After bounded derivation and archive inspection, chal.c showed a syscall 318 random value and syscall 102 user ID, followed by an unsigned sum; the container runs as UID 404.

## 解法

For each fresh service connection, obtain the challenge's random uint64 value, add the container UID modulo 2^64, and submit that value. The official page displayed Solved after the browser submission.

## 学び・再利用できる手法

A generic HTML intake must preserve authoritative platform category metadata when available.


## 参考

- https://alpacahack.com/daily/challenges/lets-analyze-system-calls?month=2026-08

## METISの記録

- 期間: 2026-11-17 01:10 JST 〜 2026-11-17 01:23 JST
- 使用アクション数: 12（native_data_transform ×1, official_flag_submission_browser ×1, read_only_artifact_analysis ×8, remote_service_stdio_bridge ×2）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-17 01:23 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 389,301 | `4f222da9d4b206645e5de6d69922156ced8d3a4d0c8a38610810ff60079662ed` |
| 01-00-lets-analyze-system-calls.tar.gz | 3,686 | `8b488af00f2041c30f6e71d9b8c3144b77f26d014ae632e4cb4c250905256d8b` |
| .metis-derived/90b463fc956548c6809d14942b18ffa6.bin | 30,720 | `c2a9f32b1ae8546d2caf247a1bc782f46babfe82d0403eb8ea431436eb4b83bf` |

### 接続先

- 34.170.146.252:61229

<sub>METIS writeup — 更新: 2026-11-17 01:34 JST</sub>
