# Programming

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 7 |
| カテゴリ | misc |
| 配点 | 110 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:37 JST） |
| Flag | `⟦answer:writeups/ksnctf/7-programming.md#1⟧` |
| タグ | misc, whitespace, esolang, polyglot |
| 問題URL | https://ksnctf.sweetduet.info/problem/7 |
| METIS run | `d7014a684aa94037a5919ceb504d4e90` |

## 概要

program.cpp は C++ として有効だが、空白・タブ・改行だけを抜き出すと Whitespace 言語のプログラムにもなっているポリグロット。C++ 側の出力 (FROG_This_is_wrong_:() はダミーで、Whitespace 側が PIN 33355524 を要求してフラグを出力する。

## 解析

C++ 部分を計算すると 'FROG' + '_This_is_wrong_:(' となり偽物。ソース中の空白類のみを抽出して Whitespace として解析すると、'PIN: ' を出力→数値入力→33355524 と比較→一致なら 'OK' と、入力から 33355454 を引いた値(=70='F')を起点に加減算を繰り返し dup/outc で文字を出力する処理だと分かる。PIN は比較定数としてプログラム内に埋め込まれている。

## 解法

1. 空白/タブ/改行のみ抽出し Whitespace 命令列にデコード (7-ws.py, 簡易インタプリタ)。
2. 命令 `push 33355524; sub; jz` から PIN=33355524 を読み取り、入力として与える。
3. 実行結果:
```
PIN: OK
⟦answer:writeups/ksnctf/7-programming.md#1⟧
```
```
../../.venv/bin/python -I 7-ws.py ../.metis-artifacts-5jkm5bl2/01-00-program.cpp
```

## 使用したスクリプト

- [7-solve.py](files/7/7-solve.py)
- [7-ws.py](files/7/7-ws.py)

## 学び・再利用できる手法

見た目が C++ でも空白が不自然に多いソースは Whitespace 等の esolang ポリグロットを疑う。C++ 側の出力が露骨にダミーなら本命は別言語。

- **空白ポリグロットの Whitespace 解釈**（misc）: ソースの空白・タブ・改行だけを抽出し Whitespace インタプリタで実行、比較定数から入力を得る
  - 適用条件: ソースに大量の不自然な空白があり、通常言語の出力が偽物に見える

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:37 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:37 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,554 | `98c32917a8d960c538c17d0c3929da19b26477f56679dd42d1b4abf2aa8ab953` |
| 01-00-program.cpp | 1,114 | `4b4cbef1aa67684b3607d7eeae7205a040c72bf78b7f6f63236038b92150c5d6` |

<sub>METIS writeup — 更新: 2026-11-13 15:57 JST</sub>
