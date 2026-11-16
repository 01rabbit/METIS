# ＼^o^／

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | no-parentheses |
| カテゴリ | misc |
| 配点 | 7.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:36 JST） |
| Flag | `Alpaca{v(^-^)v<nice!}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, jail, python |
| 問題URL | https://alpacahack.com/daily/challenges/no-parentheses |
| METIS run | `e7d851c6939245d29facca5f202dfc24` |

## 概要

入力から ( ) を除去して eval する jail。内包表記のターゲットで re.error.__class_getitem__ = eval を代入し、re.error["..."] で eval を括弧なしに呼ぶ。

## 解析

jail.py は eval(re.sub(r"[()]", "", input())) 。括弧なしでは関数呼び出しができない。一方、内包表記の for ターゲットには属性・添字を書けるため、式の中で属性代入ができる。Python 製クラス(re.error)の添字アクセスは type に __getitem__ が無いので __class_getitem__(key) を呼ぶ。

## 解法

1) [0 for re.error.__class_getitem__ in [eval]] で re.error.__class_getitem__ に eval を代入。2) re.error['...'] が eval('...') になる。3) 内側の文字列では括弧を \x28 / \x29 で表す(正規表現で除去されるのは実際の ( ) 文字のみ)。

```
[0 for re.error.__class_getitem__ in [eval]], re.error['__import__\x28"os"\x29.system\x28"cat flag.txt"\x29']
```
`metis remote pipe` で送信。

## 使用したスクリプト

- [noparen-solver.py](files/no-parenthes/noparen-solver.py)
- [noparen.payload](files/no-parenthes/noparen.payload)

## 学び・再利用できる手法

括弧禁止でも、(1) 内包表記ターゲットでの属性代入、(2) __class_getitem__ による添字経由の呼び出し、(3) 文字列エスケープで括弧を再構成、の組み合わせで任意コード実行できる。

- **Call without parentheses via __class_getitem__ assignment**（misc）: 内包表記ターゲットで Python 製クラスの __class_getitem__ に eval を代入し、Cls[文字列] で呼び出す。内側コードの括弧は \x28/\x29 で生成する
  - 適用条件: eval ベースの jail で括弧が除去/禁止されている。モジュール内に Python 製クラスが到達可能

## METISの記録

- 期間: 2026-11-13 22:33 JST 〜 2026-11-13 22:36 JST
- 使用アクション数: 9（official_flag_submission_browser ×1, read_only_artifact_analysis ×7, remote_service_solver_pipe ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:36 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,427 | `2489a353415541ad0b28020026e5990cc7dd5906ee958ba62e2186a11879edd3` |
| 01-00-no-parentheses.tar.gz | 544 | `275069763f50db3335be3a3988aae61d5adbec3395e0d511e80c59677d488d62` |
| .metis-derived/3e859cff685040f9a27f3523098e1b55.bin | 10,240 | `09c9d23152024fee14144af59ec3e162cacb5c5520e9a079caaaf80f8a4c93d8` |
| .metis-remote/ae66d384644a4e78aac8ebc7090dd362.recv | 24 | `20e23ed401cf4d63e379b57d1f3acaa61bd0058faea0f266b3346e2b149aa4ca` |

### 接続先

- 34.170.146.252:5287

<sub>METIS writeup — 更新: 2026-11-13 22:36 JST</sub>
