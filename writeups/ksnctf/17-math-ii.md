# Math II

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 17 |
| カテゴリ | misc |
| 配点 | 50 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:50 JST） |
| Flag | `⟦answer:writeups/ksnctf/17-math-ii.md#1⟧` |
| タグ | crypto, math, integer-root |
| 問題URL | https://ksnctf.sweetduet.info/problem/17 |
| METIS run | `8ab86a63a7be43cd85b9dd1dd61542d2` |

## 概要

x=y^101が整数として与えられており、法がないため整数の101乗根を取れば良い。

## 解析

問題文は法を示さず、xは約4000桁。整数の二分探索で101乗根yを求め、y^101==xが厳密に成立することを確認した。

## 解法

```python
def iroot(x,k):
    lo,hi=0,1<<(x.bit_length()//k+2)
    while lo<hi:
        m=(lo+hi+1)//2
        if m**k<=x: lo=m
        else: hi=m-1
    return lo
y=iroot(x,101); assert y**101==x
print('FLAG_%d'%y)
```
y = 545783032743911043438387247245888260273 (約128bit)。

## 使用したスクリプト

- [17-solve.py](files/17/17-solve.py)

## 学び・再利用できる手法

題名やヒントの「modulo」に惑わされず、まず法の有無を確認する。厳密なべき乗なら整数根で足りる。

- **厳密なべき乗の整数k乗根**（crypto）: 大整数を二分探索でk乗根にし、再べき乗で完全一致を検証する。
  - 適用条件: 法付きではなく整数として与えられた完全べき乗

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
| 00-problem.html | 12,848 | `809c929ee89f80bb55ec11b64e64b39ddb939468258f4a43576fb15a03df67cd` |

<sub>METIS writeup — 更新: 2026-11-13 15:56 JST</sub>
