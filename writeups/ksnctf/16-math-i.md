# Math I

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 16 |
| カテゴリ | misc |
| 配点 | 150 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:50 JST） |
| Flag | `⟦answer:writeups/ksnctf/16-math-i.md#1⟧` |
| タグ | crypto, rsa |
| 問題URL | https://ksnctf.sweetduet.info/problem/16 |
| METIS run | `fb29b909713d4e90a1824610dd599ede` |

## 概要

4096bit RSAで素因数p,qが与えられているため秘密指数を計算してcを復号し、mを16進で文字列化する。

## 解析

n=p*qを確認(一致)。e=65537, d=e^-1 mod (p-1)(q-1)。m=c^d mod n。問題の指示通り %0512x でhexデコードするとパディング付き平文が得られる。

## 解法

```python
d=pow(65537,-1,(p-1)*(q-1)); m=pow(c,d,n)
print(bytes.fromhex('%0512x'%m).strip(b'\0'))
```
平文は 'The flag is FLAG_...' の形式で、後ろにPADDINGが続く。

## 使用したスクリプト

- [16-solve.py](files/16/16-solve.py)

## 学び・再利用できる手法

素因数が与えられたらφから秘密指数を直接求めるだけ。問題文のフォーマット指定(%0512x)がそのまま復号手順になる。

- **既知の素因数によるRSA復号**（crypto）: p,qからd=e^-1 mod phiを求めpow(c,d,n)でメッセージを得る。
  - 適用条件: nの素因数が既知でeがphiと互いに素

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:50 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:50 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 12,915 | `3c1ab31baeacb9755ba13076de1fdd3ac8bd2ec6a1370fb3a37cc0bda167ffce` |

<sub>METIS writeup — 更新: 2026-11-13 15:56 JST</sub>
