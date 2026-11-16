# Vending Machine: Revised Version

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | vending-machine-revised-version |
| カテゴリ | misc |
| 配点 | 2 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:28 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/vending-machine-revised-version.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, python |
| 問題URL | https://alpacahack.com/daily/challenges/vending-machine-revised-version |
| METIS run | `f427df7c9afd489aa53f0170a84f4b4c` |

## 概要

find("") が常に 0 を返す性質を使い、空入力で在庫を先頭から pop し続けて flag に到達する。

## 解析

server.py は入力文字列を 'abcde'.find(input)==0 で検証し、在庫リスト stock.find(input) 相当で商品を取り出す。空文字列は find が 0 を返すため検証を通過し、毎回先頭要素が pop される。在庫は201個で末尾が flag。

## 解法

空行を201回送ると201回目で flag が払い出される。

```python
import sys
sys.stdout.write('\n'*201 + 'x\n')
```
`metis remote pipe` で送信。

## 使用したスクリプト

- [vending-solver.py](files/vending-mach/vending-solver.py)

## 学び・再利用できる手法

str.find('') は常に0。入力検証に find/startswith を使うと空文字で素通りする。

- **Empty-string find bypass**（misc）: find/in による検証は空文字列で常に成功することを利用する
  - 適用条件: 入力を str.find や in で検証するサービス

## METISの記録

- 期間: 2026-11-13 22:08 JST 〜 2026-11-13 22:28 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, read_only_artifact_analysis ×1, remote_service_solver_pipe ×3）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:28 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 379,080 | `d5e4b43be81e28efb67c609a605b227cc7405794e97e7bba4269d5f13bb89f43` |
| 01-00-server.py | 2,383 | `8be613efe4e332d4ca6f1f8167a4029f403cbb9df91da4454933a194c2e1eba2` |
| .metis-remote/222332a5fcaf4f71b3db40312ba15573.recv | 9,738 | `b6ad2388991ebefab04691ed70af217309c7b68b7eb1e6214914b449ddd3ee28` |

### 接続先

- 34.170.146.252:10965

<sub>METIS writeup — 更新: 2026-11-13 22:28 JST</sub>
