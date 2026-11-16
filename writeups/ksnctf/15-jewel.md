# Jewel

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 15 |
| カテゴリ | rev |
| 配点 | 250 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 13:44 JST） |
| Flag | `⟦answer:writeups/ksnctf/15-jewel.md#1⟧` |
| タグ | rev, android, apk, dex, aes-cbc, sha256, bruteforce, png, metadata |
| 問題URL | https://ksnctf.sweetduet.info/problem/15 |
| METIS run | `82edc3bbc779472f8ddf300359a12d5b` |

## 概要

Android APK の AES 鍵が IMEI 由来で、IMEI の SHA-256 ハッシュと先頭 8 桁が分かるため総当たりで復元し、復号した PNG の tEXt コメントからフラグを得る問題。

## 解析

classes.dex の onCreate を逆アセンブルすると、IMEI の先頭8桁が固定値であること、IMEI の SHA-256 (符号付き BigInteger の16進表記) が埋め込みハッシュと一致することを検査している。復号鍵は '!' + IMEI、IV は固定文字列。実機の IMEI が不要でも、探索空間は 10^7 以下 (Luhn 検査桁を使えば 10^6) なので総当たりで足りる。復号後の画像本体には『コメントにフラグがある』と書かれており、PNG の tEXt チャンクを読むとフラグが出る。

## 解法

## 手順
1. `Jewel.apk` を展開し `classes.dex` を解析 (自作の `15-dexdump.py` で逆アセンブル)。
2. `JewelActivity.onCreate` のロジック:
   - `TelephonyManager.getDeviceId()` (IMEI) を取得
   - `imei.substring(0,8) == "99999991"` を要求
   - `new BigInteger(SHA-256(imei)).toString(16) == "356280a5...a8a5"` を要求
   - 鍵 = `"!" + imei` (16 byte), IV = `kLwC29iMc4nRMuE5`, AES/CBC/PKCS5Padding で `res/raw/jewel_c.png` を復号
3. IMEI は 15 桁で先頭 8 桁が既知。残り 7 桁 (Luhn を使えば 10^6 通り) を SHA-256 で総当たりして IMEI を復元。
4. 復号した PNG の tEXt チャンク `Comment` にフラグがある。

```python
for n in range(10**6):
    s14 = "99999991%06d" % n
    imei = s14 + luhn(s14)
    if h(imei) == TARGET: break
key = ("!" + imei).encode()
```

## 使用したスクリプト

- [15-dexdump.py](files/15/15-dexdump.py)
- [15-solve.py](files/15/15-solve.py)
- [15-chunks.py](files/15/15-chunks.py)

## 学び・再利用できる手法

ハッシュ照合だけで保護された短い入力は総当たりで解ける。BigInteger.toString(16) は符号付きで先頭ゼロが落ちる点に注意。画像問題はまずチャンク/メタデータを確認する。dex は専用ツールが無くても、オペコード長表と定数テーブルから最小限の逆アセンブラを自作できる。

- **最小限の dex 逆アセンブラによる Android ロジック復元**（rev）: dex のヘッダから文字列/型/メソッド表を読み、Dalvik 命令長表で命令列を走査して定数文字列と呼び出し先を注釈付きで出力する。
  - 適用条件: apk/dex があり baksmali・jadx 等が使えない環境
- **ハッシュ照合と既知プレフィックスからの鍵 (識別子) 総当たり**（crypto）: 鍵が短い数字識別子 (IMEI) 由来で、そのハッシュと一部桁が既知の場合、残り桁を列挙してハッシュ一致で鍵を復元し AES-CBC で復号する。
  - 適用条件: 探索空間が 10^7 程度以下、チェックサム桁 (Luhn) で更に削減可能
- **PNG の tEXt チャンクにあるコメントの確認**（forensics）: 画像内の文言が示唆するメタデータの場所を PNG チャンク走査で読む。
  - 適用条件: 画像に隠し場所のヒントがある

## METISの記録

- 期間: 2026-11-13 11:58 JST 〜 2026-11-13 13:44 JST
- 使用アクション数: 23（official_flag_submission ×1, read_only_artifact_analysis ×21, scoped_web_requests ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 13:44 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,532 | `f36bf61212a5e8c77dff73f0b998c420d644a99be3263e0f0f248e92897b6f06` |
| .metis-web/dd5fcd3c4be24638ba244b285b21b2cd.apk | 130,498 | `0796e5c698c6bed4047909c06f33529a6fd2285765027f8d2af3fdd431bdeb9d` |
| .metis-derived/6b35f18babe9411e885f7e4ba2611b53.bin | 4,000 | `34a6ffea5c4411a7d2d8dd420451dd0cbd6155a4515271826cb7f39c51490358` |

<sub>METIS writeup — 更新: 2026-11-13 15:50 JST</sub>
