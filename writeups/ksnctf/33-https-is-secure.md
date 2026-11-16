# HTTPS is secure.

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 33 |
| カテゴリ | crypto |
| 配点 | 180 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:37 JST） |
| Flag | `⟦answer:writeups/ksnctf/33-https-is-secure.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, rsa, shared-prime, gcd, tls, pcap, rc4, forensics |
| 問題URL | https://ksnctf.sweetduet.info/problem/33 |
| METIS run | `b6be5e1682b147d48dd30d9c11941678` |

## 概要

pcap内のTLS(RSA鍵交換, RC4-MD5)通信を、2枚のサーバ証明書の公開鍵が共通素因数を持つことを利用して復号し、2枚のJPEGに分割されたフラグを連結して得た。

## 解析

pcapにはTCP 4本(chihiro:443, kei:443 各2本)があり、TLS1.0、暗号スイート 0x0004 (TLS_RSA_WITH_RC4_128_MD5)。各ホストのフルハンドシェイク1本と、同一session IDでの再開1本。2つの証明書(CN=chihiro, CN=kei)のRSA-2048法 n1,n2 に対し gcd(n1,n2) を計算すると1024bit素数となり、共通素因数が存在した(ヒント 'Two certificates are similar' に対応)。

## 解法

1) pcapを自前でパースしTCPをseq順に再構成、TLSレコードを分解。2) 証明書からn1,n2を取り出し p=gcd(n1,n2)、q=n/p で両秘密鍵を復元。3) ClientKeyExchangeのEncrypted PreMasterSecretをPKCS#1 v1.5で復号(先頭0x0301, 48byte)。4) TLS1.0 PRF(MD5 xor SHA1)でmaster secret→key expansionを行い、RC4鍵を導出して ChangeCipherSpec 以降のapplication dataを復号。5) 各セッションのHTTP応答は /flag.jpg(400x600 JPEG)で、1枚目に 'FLAG_txkbc' と右端で切れた文字、2枚目に左端から続く文字列 'Pbk2ZJagaXs' が描かれていた。左右に並べるとP付近で連続し、フラグは ⟦answer:writeups/ksnctf/33-https-is-secure.md#1⟧。再開セッション(favicon 404)はsession IDから同じmaster secretで復号でき内容確認のみ。

## 使用したスクリプト

- [33-parse.py](files/33/33-parse.py)
- [33-decrypt.py](files/33/33-decrypt.py)

## 学び・再利用できる手法

RSA鍵交換の暗号スイートは秘密鍵が分かれば受動的に復号できる。複数証明書の公開鍵が似ている/素数を共有する場合はgcdを最初に試す。ツールが無くてもpcap→TCP再構成→TLS PRF→RC4は短いPythonで実装できる。画像に分割されたフラグは並べて継ぎ目の文字を確認する(PとRなどの誤読に注意)。

- **RSA共通素因数(gcd)による複数証明書の鍵復元**（crypto）: 複数のRSA公開鍵の法同士のgcdを取り、1より大きければ共通素因数から双方の秘密鍵を計算する。
  - 適用条件: 同一素数を共有する2つ以上のRSA公開鍵が入手できる
- **pcapからのTLS(RSA鍵交換+RC4)手動復号**（forensics）: TCP再構成後にPMSをRSA復号し、TLS1.0 PRFでmaster secretとkey blockを導出、RC4でレコードを復号する。session ID再開も同じmaster secretで処理する。
  - 適用条件: サーバの秘密鍵が得られ、鍵交換がRSA(非PFS)でハンドシェイクがキャプチャに含まれる

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
| 00-problem.html | 8,666 | `95cf936102d5fa9898eaeb5795537ff09371c4efa314ba151acd36334ec3e82e` |
| 01-00-q33.pcap | 108,032 | `a92c7853831392b5ff82f1e77fd83e6eeb113b269f949dcfda87618890f304b7` |

<sub>METIS writeup — 更新: 2026-11-13 17:42 JST</sub>
