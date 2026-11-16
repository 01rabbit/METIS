# Perfect Cipher

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 21 |
| カテゴリ | misc |
| 配点 | 200 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:37 JST） |
| Flag | `⟦answer:writeups/ksnctf/21-perfect-cipher.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | ksnctf, crypto, mt19937, known-plaintext, jpeg |
| 問題URL | https://ksnctf.sweetduet.info/problem/21 |
| METIS run | `504c1bd35a134b1b84b7b8ac3ee5cc49` |

## 概要

MT19937 の出力でXORした暗号文。既知平文(encrypt.cpp)から内部状態を復元し、flag.enc を復号するとJPEG画像にフラグが現れる。

## 解析

encrypt.zip には encrypt.cpp、mt19937ar、encrypt.enc、flag.enc がある。同一のMT乱数列が encrypt.cpp(650ワード)→flag.jpg の順に鍵として使われる。encrypt.enc と encrypt.cpp のXORで650個の出力を得て、tempering を逆変換(untemper)して624個で状態復元できる。ただし同梱の encrypt.cpp は2015年に更新されたもので、原版とは数ワード(例: "Failed to open" の綴り部分, 594-596語付近, 198-199語)が違い、そのまま復元すると状態が部分的に誤り、flag.jpg のヘッダ(DQT/SOF/DHT)やXMPが壊れる。誤差はMTの漸化式 (lag 227=N-M) に沿って後続出力へ伝播するため、Exif領域の零パディングを既知平文として誤差パターンを観測し、状態誤差を逆算して補正した。

## 解法

1. ks[i] = encrypt.enc[i] ^ encrypt.cpp[i]、untemper して先頭624語で `random.Random.setstate` に投入。残り26語で検証。
2. flag.enc を続きの乱数で復号 → JPEG(1024x200)だがヘッダが壊れる。
3. flag.jpg の零領域の誤差E[i](i=ブロック1出力index)から、i<227は e_old[i+397]、i>=227は D=e'[i]^e'[i-227] を y=(D bit31? ((D^0x9908b0df)<<1)|1 : D<<1) に分解して e_old[i+1]の下位31bit/e_old[i]のbit31を求める。
4. 状態に補正を適用して再復号 → 末尾FFD9で正常なJPEG。画像に `⟦answer:writeups/ksnctf/21-perfect-cipher.md#1⟧` が写る(数字はガラス質、英字は黒)。
```python
def ydec(D): return (((D^A)<<1)&0xffffffff)|1 if D>>31 else (D<<1)&0xffffffff
```
フラグ(画像目視): `⟦answer:writeups/ksnctf/21-perfect-cipher.md#1⟧`

## 使用したスクリプト

- [21-solve.py](files/21/21-solve.py)
- [21-fix2.py](files/21/21-fix2.py)
- [21-fix3.py](files/21/21-fix3.py)
- [21-render.py](files/21/21-render.py)

## 学び・再利用できる手法

既知平文が原版と異なるとMT状態が部分的に誤り、誤差が lag 227 で伝播する。ファイル形式(JPEGヘッダ・Exif零パディング)を二次的な既知平文として使い、誤差から状態を補正できる。ガラス質(数字)と黒(英字)の区別で 8/g などの曖昧さを解消した。

- **MT19937 状態復元による鍵ストリーム予測**（crypto）: 既知平文XORで得た連続出力を untemper して624語で状態復元し、後続の鍵ストリームを生成して別ファイルを復号する。
  - 適用条件: 同一MTインスタンスの出力が連続して鍵に使われ、連続624ワード分の平文が既知であること。
- **状態誤差の逆算補正**（crypto）: 既知平文が一部不正確でも、後続平文の既知領域(零パディング等)での誤差パターンからMT漸化式を逆に辿って状態誤差を復元する。
  - 適用条件: 後続ストリームに既知(零など)の領域が十分あり、誤差が疎であること。

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:37 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:37 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,717 | `68a9314a59b18111a143e55ff25a998cb88adb7f9c9ef0fe52ecd98193185c3a` |
| 01-00-encrypt.zip | 86,165 | `b9756e3464c0dc3458d2713368bed6303fa8ae1570f27855843d424c6dcfea61` |

<sub>METIS writeup — 更新: 2026-11-13 16:08 JST</sub>
