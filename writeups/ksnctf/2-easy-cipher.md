# Easy Cipher

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 2 |
| カテゴリ | misc |
| 配点 | 50 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:50 JST） |
| Flag | `⟦answer:writeups/ksnctf/2-easy-cipher.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rot13, caesar |
| 問題URL | https://ksnctf.sweetduet.info/problem/2 |
| METIS run | `73e01a9114474c97971706ca1450e581` |

## 概要

問題文自体がROT13(ROT XIII)で暗号化されており、復号すると本文中にフラグが現れる。

## 解析

本文 'EBG KVVV vf n fvzcyr...' は ROT13 の自己言及的な文章。復号すると 'Flag is FLAGSwzgxBJSAMqwxxAU. Insert an underscore immediately after FLAG.' となる。

## 解法

```python
import codecs
p=codecs.decode(text,'rot13')
```
FLAGSwzgxBJSAMqwxxAU の FLAG の直後にアンダースコアを挿入して ⟦answer:writeups/ksnctf/2-easy-cipher.md#1⟧。

## 使用したスクリプト

- [2-easy-cipher.py](files/2/2-easy-cipher.py)

## 学び・再利用できる手法

復号文中の追加指示(アンダースコア挿入)まで読む。

- **ROT13の識別と復号**（crypto）: 文中の 'EBG KVVV' など頻出語のROT13像から換字式シーザー暗号を推定し復号
  - 適用条件: 英文らしい換字暗号文

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
| 00-problem.html | 8,972 | `b4d3719bbe5357fa3575fb8bc703cbe8270812c565fe74c2a34b3e9f4c4b6326` |

<sub>METIS writeup — 更新: 2026-11-13 17:31 JST</sub>
