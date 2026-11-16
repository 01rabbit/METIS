# typhoon-pythoon

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | typhoon-pythoon |
| カテゴリ | rev |
| 配点 | 4.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:42 JST） |
| Flag | `Alpaca{dis_is_the_eye_of_the_typhoon}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, python, pyc, xor |
| 問題URL | https://alpacahack.com/daily/challenges/typhoon-pythoon |
| METIS run | `625edf52ca1a4110ae0384c79dc6155f` |

## 概要

server.pyc (Python 3.10) は自身の親ディレクトリ名を鍵にして EYE_DATA を XOR 復号した文字列が答えになる。親ディレクトリ名は固定で "eye" なので静的に復号できる。

## 解析

marshal.loads で pyc を読み、python3.10 の dis で逆アセンブルした（実行はしていない）。is_inside_the_typhoon_eye は Path(__file__).resolve().parent.name が bytes([101,121,101]).decode() つまり "eye" と等しいかを検査する。reverse_the_wind は location = 親ディレクトリ名のバイト列として、i 番目の値 v に対し chr(v ^ ((i*7 + 41 + location[i % len(location)]) & 255)) を並べる。main は入力がこの結果と一致するかを判定する。つまり正解の入力 = EYE_DATA を location=b"eye" で復号した文字列で、これがそのまま flag。

## 解法

```python
D = [207, 197, 236, 194, 221, 208, 195, 183, 175, 190, 183, 178, 145, 162, 132, 159, 119, 90, 105, 94, 127, 126, 83, 73, 105, 37, 44, 46, 57, 45, 25, 11, 6, 26, 255, 237, 247]
loc = b"eye"
print(''.join(chr(v ^ ((i*7 + 41 + loc[i % 3]) & 255)) for i, v in enumerate(D)))
```
出力を AlpacaHack の提出フォームに入力して正解を確認した。

## 使用したスクリプト

- [typhoon-pythoon-solve.py](files/typhoon-pyth/typhoon-pythoon-solve.py)

## 学び・再利用できる手法

pyc は marshal + 該当バージョンの dis で静的に読める。ファイル配置（親ディレクトリ名）のような環境依存の鍵は、検査関数の定数から直接得られるので、プログラムを動かさずに復号できる。

- **Static decode of a .pyc whose key is derived from its own location**（rev）: Load the pyc with marshal under the matching Python version, disassemble with dis, and read the constants of the location check and the decode routine. Reimplement the decode with the required directory name instead of running the program.
  - 適用条件: A compiled Python file refuses to run unless placed in a specific directory and derives its expected answer from that directory name.

## METISの記録

- 期間: 2026-11-13 21:42 JST 〜 2026-11-13 21:42 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, read_only_artifact_analysis ×2）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:42 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 371,841 | `e1011170cac51f3eaf0b4993f20b9e8ca1402dfcf1b2f42610c286ca50e0e4c2` |
| 01-00-server.pyc | 1,546 | `43fbce3d00e578ace3c0d0920f1654681ca39f14d6e2d4f229046462c6c02730` |

<sub>METIS writeup — 更新: 2026-11-13 21:43 JST</sub>
