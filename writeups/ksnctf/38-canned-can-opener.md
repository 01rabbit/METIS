# Canned Can Opener

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 38 |
| カテゴリ | forensics |
| 配点 | 80 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 15:41 JST） |
| Flag | `FLAG_pY5t8qFfsSuNJS9P` |
| タグ | forensics, openssl, aes-256-cbc, jpeg, known-plaintext, pbkdf2 |
| 問題URL | https://ksnctf.sweetduet.info/problem/38 |
| METIS run | `dbbe881179d1441b8121e7ef54a0c5f7` |

## 概要

flag.jpg を自分自身の先頭行でパスワード化して openssl enc したため、実質パスワードは JPEG ヘッダ先頭10バイトだけ。未知の2バイトを総当たりして復号する。

## 解析

OpenSSL 1.1.1 の -pass file: は最初の1行のみ読み、NULで文字列終端する。JPEG/Exif ヘッダ 'FFD8FFE1 LLLL 45786966 00' の 00 でパスワードが切れるため、秘密は10バイト(うち2バイトのみ未知)に縮退する。-iter 10000 で PBKDF2-SHA256 なので鍵導出は 'Salted__' 付きヘッダのsaltから再現可能。最初の暗号ブロックのみ復号して JPEG マジックを判定すれば高速に探索できる。

## 解法

1. `openssl enc -pass file:flag.jpg` は `flag.jpg` の **先頭1行**（最初の `\n` まで、C文字列として NUL で打ち切り）をパスワードにする。
2. JPEG 先頭は `FF D8 FF E1 xx xx 45 78 69 66 00 ...`(Exif)。ここで NUL(0x00)が現れるので、パスワードは `ff d8 ff e1 LL LL 45 78 69 66` の10バイトになる（LL LL は APP1 長）。
3. 配布の `flag_canned.jpg` は同じ元画像の別版（撮影時刻が数秒違う）で、先頭ヘッダが同じ構造。APP1長 `LL LL` の2バイトのみ未知 -> 65025通り以内を全探索（0x0a,0x0d除外）。
4. 各候補で PBKDF2-HMAC-SHA256(10000回, salt=`Salted__`の8バイト) から key/iv を導出し、最初の1ブロックだけ復号して `ff d8 ff` で始まるものを探す。
5. ヒットしたパスワード `ffd8ffe1395045786966` で全体を復号 -> 有効な JPEG。画像下部に `FLAG_pY5t8qFfsSuNJS9P` が描かれている。

```python
PW = bytes.fromhex('ffd8ffe1395045786966')
km = PBKDF2HMAC(hashes.SHA256(), 48, salt, 10000).derive(PW)
plain = AES-256-CBC-decrypt(key=km[:32], iv=km[32:48], body)
```

## 使用したスクリプト

- [38-prefix.py](files/38/38-prefix.py)
- [38-search.py](files/38/38-search.py)
- [38-full.py](files/38/38-full.py)
- [38-decrypt.py](files/38/38-decrypt.py)

## 学び・再利用できる手法

パスワードファイルに任意バイナリを使う場合、改行/NULで切れる点に注意。既知フォーマットのヘッダはパスワード空間を劇的に縮める。1ブロック復号+マジック判定で総当たりを軽量化できる。文字画像の読み取りは拡大して確認。

- **Password-file truncation brute force**（forensics）: パスワードがファイル先頭行(NUL/改行で切断)になる点と既知ヘッダ構造から未知バイトのみ総当たりし、最初の暗号ブロックのマジック判定で検証する。
  - 適用条件: 暗号化鍵が既知形式のバイナリファイルから導出され、一部バイトのみ未知の場合

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 15:41 JST
- 使用アクション数: 4（official_flag_submission ×1, read_only_artifact_analysis ×1, scoped_web_requests ×2）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 15:41 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 9,077 | `12690b77587b9a817421b5360fbdad6eb642b601e4e35deeea9967da6b016f78` |
| 01-00-flag_canned.jpg | 111,076 | `ba3d2c72076f7dff4598fe0aa01ee8a4269fca0dbc31765610139de5f916d5fd` |
| .metis-web/6d2cea330de645a9b09a149f5e333dbb.enc | 149,392 | `4d2d3cf535f85e20fe62f53ee74ac424e1682814d2a7461be412026ba32f243d` |
| .metis-web/bc8f6a970e204d75a9eac584a358d89f.jpg | 111,076 | `ba3d2c72076f7dff4598fe0aa01ee8a4269fca0dbc31765610139de5f916d5fd` |

<sub>METIS writeup — 更新: 2026-11-13 15:55 JST</sub>
