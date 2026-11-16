# Almost Shared Prime

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | almost-shared-prime |
| カテゴリ | crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:39 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/almost-share-almost-shared-prime.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rsa, continued-fraction |
| 問題URL | https://alpacahack.com/daily/challenges/almost-shared-prime |
| METIS run | `78e922f1f82d48418a90d88533914d09` |

## 概要

n1=p*q1, n2=(p+2)*q2（双子素数）。n2/n1 の連分数収束分数から q2/q1 を復元し p を得る。

## 解析

q1,q2 は256bit と小さく、n2/n1 と q2/q1 の差は約2/p で 1/(2 q1^2) 未満。ルジャンドルの定理で収束分数に現れる。

## 解法

n2/n1 の連分数収束分数の分母で n1 を割り切り256bitのものが q1。p=n1/q1、(p+2)|n2 を確認し復号。

## 使用したスクリプト

- [asp-solve.py](files/almost-share/asp-solve.py)

## 学び・再利用できる手法

n1=p*q1, n2=(p+2)*q2（双子素数）。n2/n1 の連分数収束分数から q2/q1 を復元し p を得る。

- **Continued-fraction recovery of near-shared RSA primes**（crypto）: Given n1=p*q1 and n2=(p+2)*q2 with small q1,q2, the ratio n2/n1 = (q2/q1)*(1+2/p) differs from q2/q1 by ~2/p, far below 1/(2*q1^2). By Legendre's theorem q2/q1 (lowest terms) is a convergent of the continued fraction of n2/n1; the convergent whose denominator divides n1 and has the right bit-length yields q1, hence p.
  - 適用条件: Two RSA moduli sharing a prime up to a small known additive shift, with the co-factors much smaller than the shared prime.

## METISの記録

- 期間: 2026-11-13 20:31 JST 〜 2026-11-13 20:39 JST
- 使用アクション数: 2（official_flag_submission_browser ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:39 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 372,590 | `fcfb1418bcb243e4a1cfb87722cacbec6eb968c15a49e85a7bf30b19dc834ddb` |
| 01-00-almost-shared-prime.tar.gz | 1,338 | `44390a237ef9ad6adaf30eeb57c1bbf7a785933889d897ccb61a25b21171c849` |
| .metis-web/2efb7b08e8654b1c95e96ed592a7ce4b.gz | 1,338 | `44390a237ef9ad6adaf30eeb57c1bbf7a785933889d897ccb61a25b21171c849` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
