# KanGacha

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 31 |
| カテゴリ | web |
| 配点 | 130 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/31 |
| METIS run | `92042ebdb2b54bbca9f0c59828ddbfbc` |

## 概要

出題サーバー ctfq.u1tramarine.blue に到達できないため、未着手のまま保留した。

## 解析

出題サーバー ctfq.u1tramarine.blue に対して、METIS 経由の HTTP(S) リクエストや SSH が、すべてタイムアウトした。ユーザーが sandbox の外（ターミナルとブラウザ）から確認しても、全ポートでタイムアウトした。原因は sandbox ではなく、サーバー側の停止か到達不能とみられる。

## 解法

ctfq に到達不能のため未着手。flag 候補なし。

## 学び・再利用できる手法

サーバーが復旧したら、この問題を queued に戻して調査を始める。それまでは ctfq への再試行をしない。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 18:02 JST
- 使用アクション数: 5（read_only_artifact_analysis ×1, scoped_web_requests ×4）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,899 | `37ca02529bb271e5d7fe084f865cfd19d9198427bf96aca3619ed490a2c89815` |

<sub>METIS writeup — 更新: 2026-11-13 18:04 JST</sub>
