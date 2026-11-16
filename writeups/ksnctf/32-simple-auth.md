# Simple Auth

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 32 |
| カテゴリ | web |
| 配点 | 50 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/32 |
| METIS run | `a9a4c8c034ae46df9c7e88e9a4fbb4a0` |

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
| 00-problem.html | 8,879 | `5ff4db287e67c79480a6a045a494a061b8239e5d03df6e4a16dd9974536c3db9` |

<sub>METIS writeup — 更新: 2026-11-13 18:04 JST</sub>
