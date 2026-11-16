# Test Problem

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 1 |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:48 JST） |
| Flag | `⟦answer:writeups/ksnctf/1-test-problem.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | warmup |
| 問題URL | https://ksnctf.sweetduet.info/problem/1 |
| METIS run | `4c1ec41ea4b94150908820eaa337b897` |

## 概要

問題文に提出すべきフラグがそのまま書かれている。

## 解析

問題ページ(00-problem.html)の本文に FLAG_ で始まる文字列が記載されている。

## 解法

```python
import re
t=re.sub(r'<[^>]+>','\n',open('00-problem.html').read())
print(re.search(r'FLAG_\w+',t).group(0))
```
結果: ⟦answer:writeups/ksnctf/1-test-problem.md#1⟧

## 使用したスクリプト

- [1-test.py](files/1/1-test.py)

## 学び・再利用できる手法

まず問題文を読む。

- **問題文中のフラグ抽出**（misc）: HTMLからタグを除去しFLAG形式の文字列を正規表現で取り出す
  - 適用条件: フラグが本文に直接書かれている

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:48 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:48 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,745 | `4c8b19398e0b899d909779f81695f60cd1e5039c5c0633f504727d001faee952` |

<sub>METIS writeup — 更新: 2026-11-13 17:31 JST</sub>
