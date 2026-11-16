# John

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 14 |
| カテゴリ | crypto |
| 配点 | 60 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 15:39 JST） |
| Flag | `FLAG_aSiuJHSLfzoQkszD` |
| タグ | crypto, sha512crypt, dictionary-attack, shadow, ksnctf |
| 問題URL | https://ksnctf.sweetduet.info/problem/14 |
| METIS run | `01b16be7cc9d4d5aac16a4b87134e0a9` |

## 概要

shadow 形式の sha512crypt ハッシュ 21 件を配布辞書で解き、各パスワードの頭文字を連結して FLAG を得る問題。

## 解析

$6$ は sha512crypt (5000 rounds)。user99 の行は辞書 URL を示すダミー。辞書は約 3000 語で、各ユーザーのパスワードは辞書内の単語。頭文字が FLAG_ で始まることが解読の正しさの確認になる。

## 解法

```python
# 14-crack.py: sha512crypt(rounds=5000) を辞書の各語で総当たり
c = sha512_crypt(word, salt, 5000)   # 純 Python 実装 (14-sha512crypt.py)
if c == expected: found = word
```
user00..user20 の 21 件が約 45 秒で全て辞書ヒット:

`FREQUENT LATTER ADDITIONAL GENDER __________ applies SPIRITS independent ultimate JENNY HELD SUFFERS LEAVE floating zecht opinion QUESTION karaoke strange zero DELIGHT`

各パスワードの頭文字を順に連結する (大文字小文字は保持):
`F L A G _ a S i u J H S L f z o Q k s z D` -> `FLAG_aSiuJHSLfzoQkszD`

## 使用したスクリプト

- [14-crack.py](files/14/14-crack.py)
- [14-sha512crypt.py](files/14/14-sha512crypt.py)
- [14-verify.py](files/14/14-verify.py)

## 学び・再利用できる手法

辞書が配布されている場合は John/hashcat が無くても、純 Python 実装で小さな辞書なら数十秒で足りる。頭文字を拾うとき大文字小文字を変えない。ローカル検証は HMAC 塩付き digest のため、塩 (web_runs) を読まない範囲では未検証。

- **shadow ハッシュの辞書攻撃**（crypto）: sha512crypt を配布辞書の単語で総当たりし全アカウントを復元する。
  - 適用条件: 辞書が配布され、パスワードが辞書語であること。
- **復元パスワードの頭文字連結**（crypto）: 復元した語列の頭文字を順に並べて隠れた文字列を得る。
  - 適用条件: 先頭が既知の接頭辞 (FLAG_) になること。

## METISの記録

- 期間: 2026-11-12 23:49 JST 〜 2026-11-13 15:39 JST
- 使用アクション数: 5（official_flag_submission ×1, read_only_artifact_analysis ×2, sandboxed_dynamic_execution ×1, scoped_web_requests ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 15:39 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 11,533 | `85211889849b130eb533a96edfd0afacea47ab0f644ea46a802e23b349b1c5ec` |
| .metis-web/166750c76f5f413e9f0a20badff9656f.txt | 26,114 | `cd330d32f936d31ff166272d8fd80b0b1b2c6e7e1c799030daef3defbf6916b0` |

<sub>METIS writeup — 更新: 2026-11-13 15:50 JST</sub>
