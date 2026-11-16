# Onion

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 5 |
| カテゴリ | misc |
| 配点 | 70 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:50 JST） |
| Flag | `FLAG_FeLgP3SiAWezWPHu` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | encoding, base64, uuencode |
| 問題URL | https://ksnctf.sweetduet.info/problem/5 |
| METIS run | `9c39b7f65ab6476aaa3b848da1303508` |

## 概要

Base64を繰り返し(16回)デコードすると uuencode 形式が現れ、それをデコードしてフラグを得る。

## 解析

本文の長い文字列は 'Vm0w' で始まり、Base64が多重に掛かっている(Vm0w は多重Base64の典型的な先頭)。16回デコードすると 'begin 666 <data>' で始まる uuencode になる。

## 解法

```python
while True:
    try: x=base64.b64decode(d,validate=True)
    except Exception: break
    d=x
binascii.a2b_uu(line)
```
最終結果 FLAG_FeLgP3SiAWezWPHu

## 使用したスクリプト

- [5-onion.py](files/5/5-onion.py)

## 学び・再利用できる手法

デコード結果の先頭を毎回見て形式を判定する。自動ループは、終端形式(uuencode)で止まる条件を意識する。

- **多重Base64の自動剥離とuuencode**（misc）: Base64として妥当な限り反復デコードし、'begin 666' を見つけたらuudecodeする
  - 適用条件: Base64の入れ子で先頭が 'Vm0w' などの定型

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:50 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:50 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 16,263 | `7f69d9ebf8680fc40803f83b4d2c631490d3650ef6940ff495220857801cef74` |

<sub>METIS writeup — 更新: 2026-11-13 17:31 JST</sub>
