# YELL

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | yell |
| カテゴリ | crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:39 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/yell-yell.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rsa, pollard-p-1 |
| 問題URL | https://alpacahack.com/daily/challenges/yell |
| METIS run | `97863f15f6874f409285c878f10813cf` |

## 概要

p-1,q-1 の素因数（64個のcands）が開示されるため Pollard p-1 の候補別分割で素因数分解。

## 解析

p=k*p_+1, q=l*q_+1。p_,q_ は既知の64個の64bit素数のうち16個ずつの積。全体での 2^E は gcd=n になるので、cand ごとに E/x で割って片側だけ 1 になる gcd を取る。

## 解法

E=lcm(1..255)*prod(cands)。各 x について g=gcd(2^(E/x)-1,n)。非自明な g が素因数。

## 使用したスクリプト

- [yell-solve.py](files/yell/yell-solve.py)

## 学び・再利用できる手法

p-1,q-1 の素因数（64個のcands）が開示されるため Pollard p-1 の候補別分割で素因数分解。

- **Pollard p-1 with a disclosed smooth structure (per-candidate split)**（crypto）: When p-1 and q-1 are products of KNOWN small primes (disclosed by the challenge) times a tiny cofactor, a plain Pollard p-1 over all of them yields gcd=n (both sides smooth). Split instead: for each disclosed prime x compute gcd(2^(E/x)-1, n) with E=lcm(1..B)*prod(primes); if x divides only p-1 the gcd reveals one factor.
  - 適用条件: RSA where the prime factors of p-1/q-1 are leaked (e.g. printed) and shared across both primes.

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
| 00-problem.html | 368,987 | `e92348cc1f883a1149177be5057a486ea9bdfcacf71eb78cbebebc7290fa2808` |
| 01-00-yell.tar.gz | 2,061 | `867caf0fc1b806d0d3d5854ecf70b7e27bce4dfcb7e7f97c562bba4da1bf93a1` |
| .metis-web/9148df53de1a405aa4acb44ff822c56e.gz | 2,061 | `867caf0fc1b806d0d3d5854ecf70b7e27bce4dfcb7e7f97c562bba4da1bf93a1` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
