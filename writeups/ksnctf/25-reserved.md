# Reserved

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 25 |
| カテゴリ | misc |
| 配点 | 30 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:00 JST） |
| Flag | `⟦answer:writeups/ksnctf/25-reserved.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, perl, esoteric-language, static-analysis |
| 問題URL | https://ksnctf.sweetduet.info/problem/25 |
| METIS run | `3d15569d56544c78ae2f21e81b626576` |

## 概要

Perl の予約語と組み込み関数だけで書かれた文字列を、クォート演算子の字句解析と関数鎖の静的評価で復元し FLAG を得た。

## 解析

問題文の <code> 内は `length q chr uc and print chr ord uc qw q flock q and print chr oct ord q or no and ...` の形。q / qw / qq の直後に空白と任意の英字区切り文字が続くため、Perl のクォート演算子として字句解析すると、全体は `条件 and print chr F1 F2 ... Q and print ...` の並びになる。Q はクォート内容(q)か qw の単語リストで、F は ord / uc / oct / hex / length などの関数。先頭の `length Q` は 4 で真のため、以降の print はすべて実行される。各文は内側(右)の関数から順に評価して 1 文字を出力する。oct(ord(x)) は ord の 10 進文字列を 8 進として解釈する点が重要。出力の先頭は FLAG_ で始まり、その後に説明文が続く。

## 解法

1) HTML の <code> 内を取り出し、HTML エンティティを戻す。2) q/qq/qw の直後の空白の次の 1 文字を区切りとし、同じ文字まで内容を読む字句解析を行う。3) 各 `print chr` の後ろの関数列と末尾のクォート値を、内側から順に chr / ord / uc / oct / hex / length で評価する。4) 出力を連結すると ⟦answer:writeups/ksnctf/25-reserved.md#1⟧ で始まる文字列になる。Perl 本体は実行せず、Python で静的に再現した。

## 使用したスクリプト

- [25-reserved-decode.py](files/25/25-reserved-decode.py)

## 学び・再利用できる手法

予約語の列でも字句解析の規則を当てはめれば通常の式として読める。変換関数の連鎖は内側から評価する。oct / hex が数値の 10 進表記を別の基数として読む点に注意すると、文字の値を正しく再現できる。

- **クォート演算子の区切り文字による字句解析**（misc）: q や qw の直後の空白と任意の 1 文字を区切りとして読み、予約語列を式の並びに戻す
  - 適用条件: 予約語列が q や qw を含み、区切り文字が空白の直後に置かれている
- **関数鎖の内側からの静的評価**（misc）: print chr の後ろの変換関数を右から左へ適用し、1 文字ずつ出力を組み立てる
  - 適用条件: 出力文が chr と変換関数の連鎖で書かれ、末尾に値がある

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:00 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:00 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 10,155 | `14b8eefd6552fefc0a0f21b1ac6da2ed8d69726e2dadce7bd8ca368dca19e227` |

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
