# Villager A

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 4 |
| カテゴリ | rev |
| 配点 | 300 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | rev, ssh |
| 問題URL | https://ksnctf.sweetduet.info/problem/4 |
| METIS run | `16107f7ea42a411897bb7a2c8e89b6c1` |

## 概要

SSH 接続型の問題。問題文の読解と 2 回の SSH 接続（応答本文は空）で止まった。

## 解析

問題ページの本文を 3 回 read-only で解析し、SSH 接続を 2 回試行した。1 回の観測は tool_ok=false、接続側で受信できたデータは空（空データの SHA-256）だった。（イベント記録上、これ以外の試行は残っていない）

## 解法

未解決。flag 候補なし。接続先でシェルを取得できず、バイナリや仕様の取得まで進んでいない。

## 学び・再利用できる手法

次はユーザーの承認した接続情報で対話的に入れるかを再確認し、入れたら配置ファイルを取得して静的解析する。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 13:20 JST
- 使用アクション数: 5（read_only_artifact_analysis ×3, remote_ssh ×2）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,924 | `1d17c50ba3d2cd0f75e3bcdc9fe0180d59d196c510a0695b12fa680088d3ff93` |

### 接続先

- ctfq.u1tramarine.blue:10004

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
