# Bitflip RSA

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | bitflip-rsa |
| カテゴリ | crypto |
| 配点 | 7 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:43 JST） |
| Flag | `Alpaca{hit the road Bob and don't you encrypt no more}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rsa, franklin-reiter |
| 問題URL | https://alpacahack.com/daily/challenges/bitflip-rsa |
| METIS run | `0d3c1e10df20446fa340f629a4d8e0f8` |

## 概要

m と ~m (= -(m+1)) を同じ n, e=101 で暗号化した2つの暗号文から Franklin-Reiter related-message attack で平文を復元した。

## 解析

chal.py は c1 = m^101 mod n, c2 = (~m)^101 mod n を出力する。Python の ~m = -m-1 で e は奇数なので c2 = -(m+1)^101 mod n。よって x=m は f1 = x^e - c1 と f2 = (x+1)^e + c2 の共通根。Z_n 上の多項式 GCD (Euclid) を取ると一次式になり、m = -g0/g1 mod n で平文が得られる。

## 解法

1. tar.gz から chal.py と output.txt を取り出し n,e,c1,c2 を得る
2. ~m = -(m+1) より c2 = -(m+1)^e と変形
3. f1=x^101-c1, f2=(x+1)^101+c2 の多項式GCDを mod n で計算 (.metis-state/work/bitflip-solve.py)
4. 得られた一次式から m を求めバイト列に変換しフラグを得た

解法スクリプト: bitflip-solve.py

## 使用したスクリプト

- [bitflip-solve.py](files/bitflip-rsa/bitflip-solve.py)

## 学び・再利用できる手法

ビット反転 ~m は -(m+1) なので、e が奇数なら c2=-(m+1)^e。線形関係の2暗号文は Franklin-Reiter を疑う。

- **Franklin-Reiter related-message attack**（crypto）: 同一の n,e で線形関係 (m と a*m+b) にある2平文の暗号文があれば、x^e-c1 と (ax+b)^e-c2 の多項式GCDを mod n で取ると一次式になり平文が復元できる。e が小さい(~101程度まで)場合に実用的。
  - 適用条件: 同一モジュラス・同一小さい指数、平文間に既知の線形関係(ビット反転 ~m = -m-1 など)。

## METISの記録

- 期間: 2026-11-13 21:42 JST 〜 2026-11-13 21:43 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, read_only_artifact_analysis ×4）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:43 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 369,179 | `72bb7f9772f5dee67ff92c21cdf9e47a84386a8505811493ad8dfdd9a720e665` |
| 01-00-bitflip-rsa.tar.gz | 939 | `d78f2615a6b1d8133c5e1b13cad3c283218a380f22d54c2929e94fb08596896a` |

<sub>METIS writeup — 更新: 2026-11-13 21:43 JST</sub>
