# Competitive Programming

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 37 |
| カテゴリ | misc |
| 配点 | 600 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | misc, competitive-programming |
| 問題URL | https://ksnctf.sweetduet.info/problem/37 |
| METIS run | `ad2ab312df4c412caea853431fe0bc01` |

## 概要

競プロのコードをハックする問題。配布ファイルがあるが、記録上は 1 回のソルバ接続だけ。

## 解析

mirror.c と input.txt が手元にある。記録上の操作は remote_service_solver_pipe 1 回のみで、受信データは空（空データの SHA-256）だった。mirror.c の解析は記録に残っていない。

## 解法

未解決。flag 候補なし。入力を作る前の段階で止まっている。

## 学び・再利用できる手法

次は mirror.c の制約と誤答条件をローカルで解析し、反例入力を作ってから接続する。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 13:21 JST
- 使用アクション数: 1（remote_service_solver_pipe ×1）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 11,275 | `8327b8488640bd4913bfdcc8ac9da266c4011cc3bd549228a0aa51ffbdad3032` |
| 01-00-mirror.c | 842 | `7d04f6e6f08eb8cf170128dda7857fff5ee38099344074dcbf95763b72497d07` |
| 02-01-input.txt | 32 | `50b2e4ea89403aaaaaf28a99b899ed510cd6f81bcbe84dfa233c0f6873bc4c1f` |

### 接続先

- ctfq.u1tramarine.blue:10037

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
