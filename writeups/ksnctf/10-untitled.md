# #!

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 10 |
| カテゴリ | misc |
| 配点 | 20 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:53 JST） |
| Flag | `FLAG_SHEBANG` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, trivia, shebang |
| 問題URL | https://ksnctf.sweetduet.info/problem/10 |
| METIS run | `ef5d6f6691a44552bdd96fb93c65f9f8` |

## 概要

添付データなし。問題文の知識問題 (#! = shebang) で、FLAG_S?????? (大文字) に当てはまる語。ローカルデータからは導出不可で、オフライン再現はしていない。

## 解析

問題文は 'The flag is FLAG_S??????'(?は6文字、大文字)、'#!' の呼称を問う。SHEBANG は S+6文字(HEBANG) で形式に一致するため候補 FLAG_SHEBANG。ただし保存データに検証材料はなく、フラグの正否は主催側の検証に依存する。

## 解法

`#!` の名称は shebang。S + HEBANG の6文字で FLAG_S?????? に合致 → FLAG_SHEBANG (候補、オフラインでは未検証)。

## 学び・再利用できる手法

記号名を問う問題は正式名称が答えになりやすい。ただし裏取りできない場合は未再現と明記する。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:53 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:53 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,842 | `797422bf6ce1247e19352d8bec718c5057905141c06a3e640fe04c522cc23ea0` |

<sub>METIS writeup — 更新: 2026-11-13 17:31 JST</sub>
