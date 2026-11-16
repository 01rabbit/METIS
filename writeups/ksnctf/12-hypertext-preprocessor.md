# Hypertext Preprocessor

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 12 |
| カテゴリ | web |
| 配点 | 70 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/12 |
| METIS run | `d6957d29d6d042f4b1554f0f5d6062bd` |

## 概要

出題サーバー ctfq.u1tramarine.blue に到達できないため、未着手のまま保留した。

## 解析

出題サーバー ctfq.u1tramarine.blue に対して、METIS 経由の HTTP(S) リクエストや SSH が、すべてタイムアウトした。ユーザーが sandbox の外（ターミナルとブラウザ）から確認しても、全ポートでタイムアウトした。原因は sandbox ではなく、サーバー側の停止か到達不能とみられる。

## 解法

ctfq に到達不能のため未着手。flag 候補なし。

## 学び・再利用できる手法

サーバーが復旧したら、この問題を queued に戻して調査を始める。それまでは ctfq への再試行をしない。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 13:42 JST
- 使用アクション数: 1（read_only_artifact_analysis ×1）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,771 | `4555e1c51540922342b155ad0b2eb312a7d055ffd2b8a29fc02db3672f393070` |

<sub>METIS writeup — 更新: 2026-11-13 18:03 JST</sub>
