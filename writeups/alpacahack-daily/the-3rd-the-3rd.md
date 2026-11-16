# The 3rd

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | the-3rd |
| カテゴリ | crypto |
| 配点 | 7.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:46 JST） |
| Flag | `Alpaca{prprpr}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, elliptic-curve, pohlig-hellman, bsgs, crt |
| 問題URL | https://alpacahack.com/daily/challenges/the-3rd |
| METIS run | `7856b7a9357d4f089a1db63dc7df96a8` |

## 概要

楕円曲線 y^2=x^3+2x+3 を Z/(pqr) 上で扱い T=m*S が与えられる。p,q は既知の約40bit素数なので、各素数体で離散対数を解き CRT で flag を復元する。

## 解析

chal.sage: E=EllipticCurve(Zmod(p*q*r),[2,3]), T=int(flag)*S。p,q は既知、r は秘密。T,S を p,q で縮約すると F_p, F_q 上の楕円曲線 DLP になり、r は不要。flag は Alpaca{+6バイト+} なので未知は48bitのみ。

## 解法

1. 各素数 p で S mod p の位数を求める: (p+1)*S に対し Hasse 区間 [-2sqrt(p), 2sqrt(p)] で BSGS して位数の倍数を得て、素因数で縮約。ord_p = 2^3*116177*310481, ord_q = 283*29023*36809 (smooth)。
2. Pohlig-Hellman + BSGS で m mod ord_p, m mod ord_q を求め、CRT で m mod lcm (77bit) を得る。
3. 未知48bit < 77bit なので範囲内の m は一意で、バイト列に直すと flag になる。ブラウザで提出し Solved を確認。

## 学び・再利用できる手法

素数が小さいと各素因数体で DLP が現実的になり、未知の素数 r は不要。既知の flag 部分から未知ビット数を見積もり、CRT 後の法がそれを上回るか確認する。純 Python だけで数秒で解ける。


## METISの記録

- 期間: 2026-11-13 21:41 JST 〜 2026-11-13 21:46 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, read_only_artifact_analysis ×4）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:46 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 369,895 | `d7871f1ee6cccf7b065654b46650f0a02acc32bace239d898010ae269dd6fb67` |
| 01-00-the-3rd.tar.gz | 575 | `f697147e076a7bd4e38c4c276e849dda9f258a930ece2eea27270bf8858ca568` |

<sub>METIS writeup — 更新: 2026-11-13 21:46 JST</sub>
