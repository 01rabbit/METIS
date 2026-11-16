# neighboRhood_diStAnce

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | neighborhood-distance |
| カテゴリ | crypto |
| 配点 | 7 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:44 JST） |
| Flag | `Alpaca{Now_is_the_time_to_recite_those_lyrics_by_John_Lennon:'All_we_are_saying_is_give_peace_a_chance!'}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rsa, crypto, close-primes |
| 問題URL | https://alpacahack.com/daily/challenges/neighborhood-distance |
| METIS run | `b78783d6705444baa475342d7311b805` |

## 概要

3つの RSA modulus が n1=p*qq, n2=q*rr, n3=r*pp (qq=next_prime(q) 等) の形で素数を巡回共有している。n1*n3/n2 ≈ p^2 から p を近似し、小さな窓を総当たりして素因数分解する。

## 解析

pp-p, qq-q, rr-r は高々 2^16 程度 (1024bit 素数の素数間隔は平均 ~710)。よって n1*n3/n2 = p^2 (1+b/q)(1+a/p)/(1+c/r) で、補正項の相対誤差は ~2^-1008。isqrt(n1*n3//n2) は p から高々 ~2^17 しか離れない。同様に q ≈ sqrt(n2*n1/n3), r ≈ sqrt(n3*n2/n1)。

## 解法

1. `est = isqrt(n1*n3 // n2)` を中心に ±2^19 の整数 x を走査し `n1 % x == 0` となる x が p。
2. 同様に q (n2,n3,n1 の順)、r (n3,n1,n2 の順) を求める。
3. 各 n_i を 2 素因数に分解して phi を計算し e=65537 の逆元で復号。m1,m2,m3 を連結して flag を得る。

```python
est = isqrt(a*cc//b)
for x in range(est-W, est+W):
    if a % x == 0: return x
```

## 使用したスクリプト

- [nd-solve.py](files/neighborhood/nd-solve.py)
- [nd-out.json](files/neighborhood/nd-out.json)

## 学び・再利用できる手法

素数が隣接素数との積で循環的に使われていると、積の比と平方根で素数の近似値が得られる。近似精度が窓に収まるか誤差の大きさを見積もってから総当たりする。

- **Recover cyclically shared near-prime factors via sqrt of modulus ratio**（crypto）: When moduli are n1=p*q', n2=q*r', n3=r*p' with x' a small distance from x, n1*n3/n2 is approximately p^2 with relative error about 2^-(bits-16). Integer sqrt gives p within a small window; scan the window for a divisor of n1, then repeat cyclically for q and r.
  - 適用条件: Several RSA moduli built from a cycle of primes where each co-factor is next_prime of another prime (small gap), so the ratio approximation error is much smaller than the prime size.

## METISの記録

- 期間: 2026-11-13 21:43 JST 〜 2026-11-13 21:44 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, read_only_artifact_analysis ×4）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:44 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 369,458 | `3f9af6a26f8865663393ace7a2ac487d2291d252e38de1016c7efd54706ca21f` |
| 01-00-neighborhood-distance.tar.gz | 2,686 | `ca403ba9c49d7fcefaa583f4a7d14c97fc2eb3d468b5de6acb3c01e71dc2276e` |

<sub>METIS writeup — 更新: 2026-11-13 21:45 JST</sub>
