# Sherlock Holmes

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 26 |
| カテゴリ | crypto |
| 配点 | 70 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | crypto, unreachable |
| 問題URL | https://ksnctf.sweetduet.info/problem/26 |
| METIS run | `c255dff891894304899f28e3e2c3b154` |

## 概要

出題サーバー ctfq.u1tramarine.blue に到達できないため、未着手のまま保留した。

## 解析

出題サーバー ctfq.u1tramarine.blue に対して、METIS 経由の HTTP(S) リクエストや SSH が、すべてタイムアウトした。ユーザーが sandbox の外（ターミナルとブラウザ）から確認しても、全ポートでタイムアウトした。原因は sandbox ではなく、サーバー側の停止か到達不能とみられる。

## 解法

ctfq に到達不能のため未着手。flag 候補なし。

## 学び・再利用できる手法

サーバーが復旧したら、この問題を queued に戻して調査を始める。それまでは ctfq への再試行をしない。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 18:01 JST
- 使用アクション数: 3（read_only_artifact_analysis ×1, scoped_web_requests ×2）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,798 | `0e5c9409c71858c22d9266410ecf0f5a8af7aaa6150ea3a47f5f5c42bd80df79` |

<sub>METIS writeup — 更新: 2026-11-13 18:04 JST</sub>
