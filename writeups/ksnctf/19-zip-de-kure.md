# ZIP de kure

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 19 |
| カテゴリ | crypto |
| 配点 | 150 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:37 JST） |
| Flag | `⟦answer:writeups/ksnctf/19-zip-de-kure.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, zip, zipcrypto, known-plaintext, biham-kocher, jpeg |
| 問題URL | https://ksnctf.sweetduet.info/problem/19 |
| METIS run | `6fe3fd78e9d0453fac1a9e9ac8613f33` |

## 概要

flag.zip の ZipCrypto 暗号化 JPEG の先頭 JFIF ヘッダ12バイトを既知平文として Biham-Kocher 攻撃で鍵を復元し flag.html を復号した。

## 解析

flag.zip は中央ディレクトリ欠損・データ記述子付きで、flag.html(304B) と Standard-lock-key.jpg の2エントリが無圧縮 ZipCrypto で暗号化されている。短い辞書・6桁以下の数字ではパスワードが見つからない。JPEG の先頭は FFD8FFE0 0010 'JFIF' 00 01 の12バイトとほぼ確実に既知なので、既知平文攻撃が成立する。

## 解法

鍵ストリーム k=c^p から z の bit2..15 を 2^22 通りに絞り、crc32 逆算で z_i と msb(y_i) を8bit確定。y の LCG と x の crc 連鎖(下位バイト4個で x が決まる)を使い pivot の 2^16 通りを列挙して整合を取る C 実装(19-zipattack.c)を14並列で実行。合成データで鍵一致を確認後、実データで鍵状態(パスワード処理直後)を復元し、19-decrypt.py で flag.html を復号。CRC-32 一致を確認し FLAG_ を得た。

## 使用したスクリプト

- [19-zipattack.c](files/19/19-zipattack.c)
- [19-decrypt.py](files/19/19-decrypt.py)
- [19-synth-test.py](files/19/19-synth-test.py)
- [19-zipcrypto-dict.py](files/19/19-zipcrypto-dict.py)

## 学び・再利用できる手法

ZipCrypto は既知平文12バイトで鍵が復元できパスワード不要。ZIP 内の画像などマジックバイトが決まるファイルが狙い目。先に合成データで攻撃コードを検証し、CRC で結果確認する。ASCIIアートは無関係。

- **ZipCrypto 既知平文攻撃(Biham-Kocher)**（crypto）: 連続12バイト以上の既知平文から内部鍵3個を復元し、パスワードなしで同一パスワードの全エントリを復号する。
  - 適用条件: 従来型ZipCrypto、既知平文12バイト以上(うち連続8以上)
- **ファイル形式のマジックバイトを既知平文に使う**（misc）: 暗号化アーカイブ内の JPEG/PNG 等は先頭ヘッダが固定なので既知平文として使える。
  - 適用条件: 暗号化エントリが無圧縮(stored)で先頭位置が分かる
- **自作攻撃コードの合成データ検証**（misc）: 既知パスワードで生成した合成サンプルに対し攻撃を限定範囲で走らせ、復元鍵が一致することを確認してから本番を回す。
  - 適用条件: 探索が長時間になる自作ツール

## METISの記録

- 期間: 2026-11-12 23:53 JST 〜 2026-11-13 00:37 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:37 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 10,735 | `aa4524a217bbd9a26b5c07c56737ebc7bdcd714af9ce92244f04cedd963678ad` |
| 01-00-flag.zip | 245,461 | `3b3382353aafdc7c2b5db036c1c532e493ab51025532fe5f37c989cfd4879072` |

<sub>METIS writeup — 更新: 2026-11-13 18:06 JST</sub>
