# Private BBS

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 41 |
| カテゴリ | web |
| 配点 | 80 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/41 |
| METIS run | `ff8b501a2802453c840616a83ac6f816` |

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
| 00-problem.html | 9,648 | `5c133c0afaa12a60d002a371e99459ebb5d9cf823fec2cf6e4476f20b7d70cf5` |
| 01-00-pbbs.zip | 212,693 | `f47595982bd3ca433b77b49c9b4e16625a7340e642a132bd913d69ba36edee37` |
| 02-01-index.html.txt | 6,371 | `529e5decc9c87fc0439accf2acedbf6193a6c471e86fdac374f03a3d80013bb5` |

<sub>METIS writeup — 更新: 2026-11-13 18:04 JST</sub>
