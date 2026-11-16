# nested eval

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | nested-eval |
| カテゴリ | misc |
| 配点 | 6.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:29 JST） |
| Flag | `Alpaca{jail_tsukurun0_taihenda}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, jail, python |
| 問題URL | https://alpacahack.com/daily/challenges/nested-eval |
| METIS run | `0c18fb5878a34510ac883f2e7eac048a` |

## 概要

eval(f"eval({code})") の jail。禁止文字 ( ) \ + __ を f-string の {N:c} で chr 生成して回避し、内側 eval で任意式を実行する。

## 解析

入力 code は ASCII のみ、かつ ( ) \ + __ を含めない。外側 eval は eval(<code>) を評価し、<code> の値(文字列)を内側 eval が評価する。flag は /flag-<md5>.txt で名前不明のため glob が必要。

## 解法

code を f"{112:c}{114:c}..." の形にすると、括弧等を含まないまま、値が print(open(__import__("glob").glob("/flag*")[0]).read()) の文字列になる。内側 eval がそれを実行して flag を出力。

## 使用したスクリプト

- [nested-solver.py](files/nested-eval/nested-solver.py)
- [nested.payload](files/nested-eval/nested.payload)

## 学び・再利用できる手法

文字フィルタ型 jail は f-string の format spec ({N:c}) で任意文字を生成でき、二重 eval なら生成文字列がそのまま実行される。

- **f-string chr generation to bypass character blacklist**（misc）: f-string の {N:c} で禁止文字を生成し、二重 eval で実行させる
  - 適用条件: eval 系の jail で文字ブラックリストがある

## METISの記録

- 期間: 2026-11-13 21:48 JST 〜 2026-11-13 22:29 JST
- 使用アクション数: 17（official_flag_submission_browser ×1, read_only_artifact_analysis ×15, remote_service_solver_pipe ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:29 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,312 | `11798569887d2a1bd104b7606cbf360c9ca58f960bb9a27c0042425ba1d419b6` |
| 01-00-nested-eval.tar.gz | 704 | `480a77112b8b83f15c4b1a09e19103842ecc890de81d59d98151cf3bb4058543` |
| .metis-derived/91e3857ee1494ee6b12d2f938dbc0b70.bin | 10,240 | `673acbd7dde32fc15f64f320715f055a0a70b174bc0343fe2e86c0da30f0c811` |
| .metis-remote/9bdfee2431b84eed93e4bcd3a440e563.recv | 38 | `4dacf57c6cb627d3b062dfa1ace090cdd71e1797575c41ed70734dd59e6f713e` |

### 接続先

- 34.170.146.252:8378

<sub>METIS writeup — 更新: 2026-11-13 22:29 JST</sub>
