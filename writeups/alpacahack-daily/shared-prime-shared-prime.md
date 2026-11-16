# Shared Prime

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | shared-prime |
| カテゴリ | crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:30 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/shared-prime-shared-prime.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rsa, gcd |
| 問題URL | https://alpacahack.com/daily/challenges/shared-prime |
| METIS run | `fbbc7acdfa724891938b201c350979e6` |

## 概要

n1,n2 が素数 p を共有するため gcd(n1,n2)=p で両者を素因数分解し復号。

## 解析

chall.py: p=getPrime(1024) を共有し n1=p*q1, n2=p*q2。出力の n1,n2 の gcd が p。

## 解法

gcd(n1,n2)=p -> q=n1//p -> d=e^{-1} mod (p-1)(q-1) -> m=c1^d mod n1。

## 使用したスクリプト

- [sprime-solve.py](files/shared-prime/sprime-solve.py)

## 学び・再利用できる手法

n1,n2 が素数 p を共有するため gcd(n1,n2)=p で両者を素因数分解し復号。

- **Shared-prime RSA factoring by GCD**（crypto）: If two RSA moduli share a prime factor, gcd(n1,n2) recovers it instantly; divide out to get the other factors and decrypt.
  - 適用条件: Two moduli generated with a common prime.

## METISの記録

- 期間: 2026-11-13 20:07 JST 〜 2026-11-13 20:30 JST
- 使用アクション数: 1（official_flag_submission_browser ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:30 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 369,691 | `d1a1ff623f047c59bbb74586c27061ee94e7cd992b720974efcf59572606056c` |
| 01-00-shared-prime.tar.gz | 1,779 | `d59ed08c741f7409b2e83a63c2e32e13896e039d2ea83ba829f700518fe38365` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
