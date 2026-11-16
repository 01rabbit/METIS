# Secret (sigma)

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | sigma-secret |
| カテゴリ | crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:41 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/sigma-secret-secret-sigma.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, math, power-sums |
| 問題URL | https://alpacahack.com/daily/challenges/sigma-secret |
| METIS run | `3e73d99b16d34220abdf5cdfd93437be` |

## 概要

各8バイトブロックで [x+y, x^2+y^2] を出力。冪和から x,y を2次方程式で復元。

## 解析

x=先頭4バイト, y=2^32+後4バイト。s1=x+y, s2=x^2+y^2 -> xy=(s1^2-s2)/2 -> t^2-s1 t+xy=0 の根。

## 解法

サーバー出力の各リストを解いて x(4B)+（y-2^32）(4B) を連結、末尾NULを除去。

## 使用したスクリプト

- [sigma-solve.py](files/sigma-secret/sigma-solve.py)

## 学び・再利用できる手法

各8バイトブロックで [x+y, x^2+y^2] を出力。冪和から x,y を2次方程式で復元。

- **Recover two values from their power sums (p1,p2)**（crypto）: Given s1=x+y and s2=x^2+y^2, xy=(s1^2-s2)/2, so x,y are the roots of t^2 - s1 t + xy = 0; pick the root in the expected range. Used to invert a per-block 'sum of k-th powers' encoding.
  - 適用条件: An encoding that leaks symmetric power sums of a small number of unknowns per block.

## METISの記録

- 期間: 2026-11-13 20:31 JST 〜 2026-11-13 20:41 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, remote_service_exchange ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:41 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,863 | `e95cfc1cb612f1a5ff8cd82ef09157f78b5f4858ec70ee31a39a7794f866d21b` |
| 01-00-sigma-secret.tar.gz | 749 | `0c9d79be0026c3b8ec0cdf3475624c02f9466d181cd0e51d664438c3ddd3f577` |
| .metis-web/679249f41bcb47cda656e9039fe44097.gz | 749 | `0c9d79be0026c3b8ec0cdf3475624c02f9466d181cd0e51d664438c3ddd3f577` |
| .metis-remote/04c9729a21cb4238872c891bc030fcdd.recv | 175 | `c4033b2989efeb68094d27826d7156ce52d2b2ceacbe05888233d3d58a12ac40` |
| .metis-remote/6827fdea6bc94ea4b0b1fbeb2e60dd1d.json | 406 | `888cdad82392a348b73ede916e522fd7cd775792bd2fb1b8bbb92497146cbd0b` |

### 接続先

- 34.170.146.252:59804

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
