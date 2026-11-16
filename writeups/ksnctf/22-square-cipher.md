# Square Cipher

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 22 |
| カテゴリ | misc |
| 配点 | 60 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:00 JST） |
| Flag | `⟦answer:writeups/ksnctf/22-square-cipher.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | ksnctf, crypto, qr, steganography, case-encoding |
| 問題URL | https://ksnctf.sweetduet.info/problem/22 |
| METIS run | `1ead13bbda3d4937a8c5d7beee3c75d3` |

## 概要

31x31 の英字格子。大文字/小文字を白黒とみて内側29x29をQRコード(version 3, ECC Q, mask 1)として読むとフラグ。

## 解析

外周1マスは全て小文字で、(1..7,1..7)等の角に7x7の同心正方形(大文字=黒,小文字=白)があり、QRのファインダパターンと一致した。外周が静寂領域、内側が 29x29=version 3。大文字=1として行列化し、形式情報(BCH距離0, ECC=Q, mask=1)を確認。ライブラリ無しで自作デコーダ(データ領域のジグザグ読み、マスク解除、2ブロックのデインターリーブ、バイトモード解析)を書いた。

## 解法

```python
M0=[[1 if rows[y+1][x+1].isupper() else 0 for x in range(29)] for y in range(29)]
# format bits -> (ecl=Q, mask=1); unmask; zigzag read; deinterleave blocks cw[0:34:2]+cw[1:34:2]
```
結果(バイトモード17バイト): `⟦answer:writeups/ksnctf/22-square-cipher.md#1⟧`

## 使用したスクリプト

- [22-solve.py](files/22/22-solve.py)
- [22-qr.py](files/22/22-qr.py)
- [22-explore.py](files/22/22-explore.py)

## 学び・再利用できる手法

大文字小文字の分布が不自然に構造的なときは1ビット画像を疑う。四隅の7x7同心正方形はQRのサイン。環境にQRライブラリが無くてもversion 3程度なら自作デコードできる。データのデインターリーブ順に注意。

- **文字ケースで符号化された1ビット画像(QR)の検出**（misc）: 格子状テキストの大小文字マスクを可視化し、角の7x7パターンからQRと判定、形式情報で版・誤り訂正・マスクを特定してデコードする。
  - 適用条件: 正方格子で大小文字の配置に空間的構造がある。

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:00 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:00 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 9,709 | `86270f6fbe5a608f2c04d3c480dd1eb511a73b5572e9ea89f6d4ee643bc521e9` |

<sub>METIS writeup — 更新: 2026-11-13 16:08 JST</sub>
