# Issue #17 証明書解析ツールの検証（2026-11-16）

## 追加したもの

- `x509`: DER または PEM（複数可）の証明書から、subject・issuer・serial・有効期間・署名アルゴリズム・
  SHA-256・公開鍵を返す。RSA なら `n`（10 進と 16 進）・`e`・ビット長、EC なら曲線名と座標を返す。
- `tls_certificates`: PCAP / PCAPNG の TCP ストリームを、シーケンス番号順に組み直して再構成する。
  TLS（SSL 3.0〜TLS 1.2）の Certificate handshake から、接続ごとの証明書チェーンを返す。版・cipher suite・
  session ID も返し、再開セッションには `resumed_from` で元の接続を示す。
- 失敗は理由コードで返す: `not_der_or_pem`、`der_parse_error`、`certificate_limit`、`not_tls_records`、
  `no_tls_handshake`、`no_certificate_message`、`tls13_certificates_encrypted`、`connection_limit`。
- 2 つとも通常の artifact tool として `ARTIFACT_TOOLS` と `ALLOWED_OPTIONS` に登録したので、予算・監査・
  重複制御・専門家 intent の経路にそのまま乗る。crypto と forensics の playbook でも推奨ツールに加えた。

## ksnctf #33 の配布 PCAP による回帰

配布 PCAP は Git に入れていない。復号できる答えをリポジトリに置くことになり、#15 の方針と衝突するためである。
`METIS_TEST_KSNCTF33_PCAP` にパスを指定すると、`test_ksnctf_33_capture_yields_two_rsa_leaf_certificates` が
実行される。ローカルで実行して合格した。内容は次のとおり。

- 2048 bit・e=65537 の葉証明書が 2 枚取れる。
- 2 枚の法の gcd が非自明になる。
- 再開セッション 2 本が、元の接続に対応づけられる。

常時実行されるテストは、テスト内で生成した証明書と合成の TLS 1.0 キャプチャを使う。共有素数の鍵、
順序の入れ替わった TCP セグメント、2 レコードに分割された handshake、再開セッション、TLS 1.3、
不正な入力を含む。

## 実 Codex による確認

新しい DB に #33 の PCAP を取り込み、`--note` なしで crypto 担当と triage 担当を動かした
（codex-cli 0.166.0）。

- crypto 担当は 4 ターンで completed（supported）。`pcap` → `tls_certificates` → `gcd`（2 つの法）と自分で進み、
  1024 bit の公約数を得た。報告では、次の手として ClientKeyExchange の取り出しと `rsa_decrypt` を挙げた。
  E2E 当時（PR #18）は、hex 窓から法を取り出せずに止まっていた段階である。
- triage 担当の 1 回目は、`tls_certificates` までは実行したが、報告に長い数値列を書いて 4 回拒否され、
  ターン切れで失敗した。拒否された報告に直し方（`how_to_fix`）を返すようドライバを修正し、retry した
  2 回目は 4 ターンで completed になった。2 回目は報告が拒否されなかったため、直し方の経路は単体テスト
  でしか通っていない。

## 残る範囲

TLS セッションの復号（PreMasterSecret から PRF、鍵ブロック、レコード復号まで）を行う METIS ツールは無い。
#33 を最後まで専門家だけで解くには、まだ Daybreak の作業が要る。
