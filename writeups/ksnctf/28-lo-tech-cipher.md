# Lo-Tech Cipher

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 28 |
| カテゴリ | crypto |
| 配点 | 60 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:59 JST） |
| Flag | `FLAG_xWqGGiTkpQpF43mp` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, visual-cryptography, polyglot, png, zip, xor |
| 問題URL | https://ksnctf.sweetduet.info/problem/28 |
| METIS run | `7f04416eb19d4633bd578b77c6294e2e` |

## 概要

secret.zip は PNG 本体にZIPが連結されたpolyglotで、ZIP内の2枚と PNG 自身の計3枚を XOR する視覚暗号。

## 解析

file で secret.zip は実体が PNG(640x480) と判明。zipfile は末尾の ZIP を読め share1.png / share2.png が出る。2枚を XOR すると下部に 'The last share is hidden in the ZIP' と出て、残り1枚(share3)の存在を示唆。PNG 自身が share3 だった。

## 解法

PNG デコーダを自作(zlib+フィルタ復元)し、share1・share2・ZIP自身のPNGの3枚を画素ごとに XOR して PNG 出力。画像上部にフラグが現れる。

## 使用したスクリプト

- [28-vcrypto.py](files/28/28-vcrypto.py)

## 学び・再利用できる手法

拡張子を信用せず file/マジックで実体を確認する。視覚暗号は XOR/AND を試し、画像内ヒントから不足シェアを探す。フラグ文字の見た目は l/I 等が曖昧なので公式入力で確認する。

- **PNG+ZIP polyglot からの追加シェア発見**（misc）: 拡張子がzipでも実体がPNGで、ZIPが末尾連結されている場合、外側ファイル自体も素材として扱う。
  - 適用条件: file が画像と判定しつつ zipfile でも開ける
- **視覚暗号シェアの XOR 合成**（crypto）: 複数の2値画像を画素ごとに XOR/AND して隠し画像を復元。途中結果の文字ヒントで不足シェアを推定する。
  - 適用条件: 同サイズの白黒ノイズ画像が複数ある

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:59 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:59 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,561 | `34f8cc9d098838a554ba82c317aa34a0c5b1d9a7f8683a633710bba5ee9923fd` |
| 01-00-secret.zip | 282,561 | `c2ca9f855fac3e7a1c141dc5e2d6f5199acb4d1bb1f9200d19518b3bc100a460` |

<sub>METIS writeup — 更新: 2026-11-13 17:41 JST</sub>
