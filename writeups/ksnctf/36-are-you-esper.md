# Are you ESPer?

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 36 |
| カテゴリ | misc |
| 配点 | 120 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | misc, remote |
| 問題URL | https://ksnctf.sweetduet.info/problem/36 |
| METIS run | `7c93b15431b246dca55c6b81a6d10b76` |

## 概要

nc / TLS で動く対話型の問題。1 回のリモート接続で、受信データが空だった。

## 解析

remote_service_exchange を 1 回行い、受信データは空（空データの SHA-256）だった。（イベント記録上、これ以外の試行は残っていない）

## 解法

未解決。flag 候補なし。サービスとの対話が始まらず、問題の形式を把握できていない。

## 学び・再利用できる手法

次は接続先の挙動（バナー、タイムアウト、TLS 側）を確認し、ESP の意味を問題文から読み直す。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 13:39 JST
- 使用アクション数: 1（remote_service_exchange ×1）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,689 | `6cd77bb789ca645773635c153bec73eefe7e3c0b20888bcd9c522148e8e9c02e` |

### 接続先

- ctfq.u1tramarine.blue:10777

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
