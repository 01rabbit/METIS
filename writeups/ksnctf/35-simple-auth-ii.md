# Simple Auth II

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 35 |
| カテゴリ | web |
| 配点 | 20 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/35 |
| METIS run | `b29975ac185643f298f4bd65d4003edb` |

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
| 00-problem.html | 8,888 | `ea2d66724b22ea0a7262c5290b6d96d93dbf9ad98b5ad952f92723fda2657433` |

<sub>METIS writeup — 更新: 2026-11-13 18:04 JST</sub>
