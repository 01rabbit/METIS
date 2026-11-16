# Crawling Chaos

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 3 |
| カテゴリ | misc |
| 配点 | 100 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:00 JST） |
| Flag | `⟦answer:writeups/ksnctf/3-crawling-chaos.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | javascript, jjencode, obfuscation, static-decoding, ksnctf |
| 問題URL | https://ksnctf.sweetduet.info/problem/3 |
| METIS run | `18dc1c927be44a2c9a130e2e532e748b` |

## 概要

unya.html の難読化JS(jjencode系の絵文字/日本語識別子版)を静的にPythonでデコードし、検証ロジックから逆算してフラグを得た。

## 解析

スクリプトは jjencode と同型。ASCII数字0-9に対応する識別子、true/false/[object Object]/undefined の文字列化から a-f,n,o,r,s,t,u,c を抜き出し、'\u00' + 16進桁を連結して 'return"\u0024..."' を作り Function コンストラクタで実行する構造。連結部分を静的に評価し \u00XX を展開すると jQuery の submit ハンドラが現れ、入力文字 t の charCodeAt(i)*(i+1) が配列 p[i] と一致するか検査していた。

## 解法

p[i]/(i+1) を文字コードとして並べると21文字の文字列になる(全要素割り切れる)。

## 使用したスクリプト

- [3-decode.py](files/3/3-decode.py)
- [3-final.py](files/3/3-final.py)
- [3-flag.py](files/3/3-flag.py)

## 学び・再利用できる手法

jjencode系は実行せず、識別子表と文字列化由来の文字テーブルを再現すれば静的にデコードできる。最終的な検証ロジックは単純な線形式であることが多い。

- **jjencode系難読化の静的デコード**（misc）: 識別子表と true/false/[object Object]/undefined の文字列インデックスから文字テーブルを再構築し、連結したペイロードを実行せずに展開する
  - 適用条件: 記号/特殊識別子のみで構成されたJS、実行禁止環境
- **線形チェックの逆算**（misc）: 入力文字コード×位置 = 定数配列 の検査を除算で逆算して入力を復元する
  - 適用条件: 検証式が可逆な算術で与えられている

## METISの記録

- 期間: 2026-11-12 23:49 JST 〜 2026-11-13 00:00 JST
- 使用アクション数: 3（official_flag_submission ×1, remote_service_solver_pipe ×2）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:00 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,557 | `58a64d9e6ed6887955faac51652a0a6cdf42dafb5634975e9bf3835c19940d3f` |

### 接続先

- ksnctf.sweetduet.info:443 (TLS)

<sub>METIS writeup — 更新: 2026-11-13 18:11 JST</sub>
