# 暗号化された証拠の入力契約と検証

提供済み artifact と明示的に許可された鍵のみを扱う。未知の鍵を第三者サービスへ照会したり、
認証情報の探索・総当たり・oracle・暗号方式の悪用を行わない。鍵は private reference で指定し、
message、CLI 引数、共有結果へ値を出さない。METIS に汎用復号器が組み込まれているという意味ではない。

## 復号前に記録する座標

| 対象 | 必須の具体値と所在 | 欠けた場合 |
| --- | --- | --- |
| Container / encoding | artifact hash、header version、member/record、ciphertext byte range、hex/base64 等の encoding、decoded 長 | terminal echo、escape 表現、部分 packet を ciphertext 全体としない。変換の前後を別 hash にする |
| 整数で渡された値 | field 名、radix、signedness、byte order、固定 byte 長。RSA なら公開 `n`/`e`、ciphertext `c` の表現を区別 | decimal text の桁数は byte 長ではない。integer 化で消えた leading zero を推測復元しない |
| 対称暗号 | algorithm、mode、key length、IV/nonce の範囲と長さ、block size、padding、counter 構成 | mode を file entropy や可読出力で決めない。AES-CBC の IV と AES-GCM の nonce を交換可能な入力としない |
| CFB 等の追加設定 | 実装・版、`segment_size` の bits、初期 IV と stream/framing boundary | API の既定を確認する。PyCryptodome の CFB は既定 8 bits であり、AES block size が 128 bits だからと 128 に読み替えない |
| 認証 | AEAD tag の位置/長さ、associated data の exact bytes と順序、MAC 対象範囲 | tag 不在/不一致、AAD 相違、truncation は認証未確認。先に出てきた plaintext を確認済みとして利用しない |
| KDF | PBKDF2 の salt、iteration count、PRF/hash、derived-key length。scrypt の `N`, `r`, `p` と salt/長さ。利用 format が要求する他 parameter | password text の encoding/normalization を含め、不明を library default で埋めない。resource limits を先に宣言する |
| 公開鍵 container | scheme、key identity、padding。OAEP なら hash、MGF/hash、label の exact bytes | RSA という名称だけで padding を選ばない。署名検証と復号を同じ操作として扱わない |

[Classic cipher modes](https://pycryptodome.readthedocs.io/en/latest/src/cipher/classic.html) と
[authenticated modes](https://pycryptodome.readthedocs.io/en/latest/src/cipher/modern.html) で、
利用する実装の parameter と成功/失敗条件を確認する。文書化された default も取得環境の版と照合する。
[KDF parameters](https://pycryptodome.readthedocs.io/en/latest/src/protocol/kdf.html) と
[OAEP parameters](https://pycryptodome.readthedocs.io/en/latest/src/cipher/oaep.html) も scheme 別に確認する。

## 完全性の判定

1. 復号対象の全範囲、header/footer、member 数、圧縮層、欠損・重複を inventory にする。
2. 許可された入力で offline 変換し、使用した仕様・tool/version・parameter の秘密でない識別情報を残す。
3. AEAD/MAC を検証してから内容を解析する。unauthenticated mode では container の長さ、構造、checksum を確認しても暗号学的な真正性は証明できない。
4. 認証済み全体、構造のみ整合、部分的候補、未復号、入力不足を別 status にする。printable bytes や正しい padding だけで「復旧成功」としない。

既知の無害な vector と tag mismatch/truncated input などの有限 fixture で、失敗が成功へ変わらないことを確認する。
特に欠損 block、部分 memory fragment、file boundary 不明の carve は対象全体の復旧と分ける。
原文や鍵を公開せず、復旧した object の数・hash、未解決 object、認証状態を owner に返す。

## 通信・設計レビューへ結ぶとき

nonce の重複は同じ key identity と mode の範囲で比べる。異なる key の同じ nonce を直ちに危険な
再利用と数えない。randomness や certificate validation の問題は、設定・コード・実際の trace を
区別する。TLS packet の暗号文だけでは application plaintext は観測していない。
stream reassembly と protocol version を確認し、private key があるという理由だけで全 TLS session が
復号可能とはみなさない。認可された session-secret material が不足すれば encrypted/unknown を維持する。

## Wallet artifact の所在と露出の確認

既存の取得物を対象に、application、OS、profile、datadir 設定を確認してから所在を解決する。
ファイル内容にある秘密を取り出すことと、ファイルへの不審なアクセスを立証することは別の調査である。

| Application | 既定位置・解決条件 | 保存する座標 |
| --- | --- | --- |
| Electrum | Linux/macOS は `~/.electrum`、Windows は `%APPDATA%\Electrum` の下の `wallets` が既定候補。起動設定による変更も調べる | user/profile、実際の datadir、wallet member、取得 hash |
| Bitcoin Core | Linux `~/.bitcoin`、macOS `~/Library/Application Support/Bitcoin`、Windows `%LOCALAPPDATA%\Bitcoin`。chain 別の datadir と `-datadir`/`-walletdir`/`-wallet` 指定を解決する | `wallets` または版・設定に応じた datadir 内の `wallet.dat`。BDB/SQLite を名前だけで判定しない |
| Geth | 対象環境の datadir と `--keystore` 設定から keystore を特定する | keystore file の所在/hash、format/version、秘密でない識別情報。既定 path だけの検索を全体調査としない |

[Electrum datadir](https://electrum.readthedocs.io/en/latest/faq.html)、
[Bitcoin Core 29 filesystem](https://raw.githubusercontent.com/bitcoin/bitcoin/v29.0/doc/files.md)、
[Geth keystore option](https://geth.ethereum.org/docs/fundamentals/command-line-options) を環境の版と照合する。

file-access telemetry では process identity/start、user、path、operation、成否、event 時刻を結ぶ。
wallet 本体以外にも backup、indexer、security tool が読むことがある。filename pattern や存在のみを
秘密の露出、読み取り成功、外部送信の証明にしない。報告は秘密を伏せた artifact 座標とアクセス証拠にする。

Recovery phrase は単語数・wordlist・外観だけで方式を特定できない。BIP39 と Electrum の versioned seed
は異なる規約であり、checksum 判定も排他的な classifier とは限らない。BIP39 の最後の単語には entropy
由来の bit と checksum bit が入るため、単語全体を独立した checksum と説明しない。提供された generator、
wallet/version、language、normalization、passphrase 使用の有無という metadata を優先し、不明を保持する。
語句・鍵をログへ出さず、方式確認のための秘密の導出、残高照会、署名、送金を行わない。
[BIP39](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki) と
[Electrum seed-version system](https://electrum.readthedocs.io/en/latest/seedphrase.html)

## Traditional ZIP metadata and limited header checks

For an acquired ZIP, retain local-header and central-directory coordinates, `general purpose bit flag`, compression method, CRC-32 and both size fields. Flag bit numbers are zero-based: bit 0 indicates encryption; bit 3 indicates a data descriptor. Under the ordinary descriptor contract, zero CRC/size placeholders in the local header are not evidence of an empty member. Resolve descriptor and central-directory values, ZIP64 sizes and encryption-specific exceptions before comparing lengths. Compressed size includes an encryption header when present.
[ZIP APPNOTE 6.3.10](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT).

The CPython 3.14 traditional-encryption reader uses a 12-byte encryption header. Its final decoded check byte is compared with the high byte of the DOS time field when `flag_bits` bit 3 is set, otherwise with the high byte of `CRC`. Preserve raw time bits instead of substituting a displayed date or Unix timestamp. This is a versioned reader check, not an AES-member rule or cryptographic authentication. A short header check alone cannot validate the full member; retain complete decoding, length and CRC results separately. No credential search or decoder is provided here.
[Versioned ZIP reader](https://github.com/python/cpython/blob/v3.14.0/Lib/zipfile/__init__.py).
