# Issue #23 TLS RSA 鍵交換セッションの復号（2026-11-16）

## 追加したもの

- `core/ctf_tls.py`、artifact tool 2 種。どちらも予算・監査・重複制御・専門家 intent の経路に乗る。
  - `tls_decrypt{factor,packets,connections,preview}`
    - 入力はサーバー証明書の RSA 法の素因数 1 つ（10 進文字列。`gcd` の結果をそのまま使う）。
    - 秘密鍵の再構成、ClientKeyExchange の PKCS#1 v1.5 復号、PRF（TLS 1.0/1.1 は MD5+SHA1、TLS 1.2 は SHA-256/384）による
      master secret（拡張マスターシークレットを含む）と鍵ブロックの導出、レコードの復号を行う。
    - 全レコードの MAC または GCM タグを検証する。
    - 再開セッションは session ID またはセッションチケットで、元のフルハンドシェイクに対応づける。
    - 接続ごとに HTTP メッセージの一覧を返す。
  - `tls_http_body{factor,connection,side,message,max_bytes}`: `derive` から使い、復号した HTTP 本文 1 つを新しい artifact
    として登録する（画像には `.jpg` などの拡張子を付ける）。
- 対応する cipher suite: RC4-128-MD5、RC4-128-SHA、AES-128/256-CBC-SHA、AES-128/256-CBC-SHA256、AES-128-GCM-SHA256、
  AES-256-GCM-SHA384（いずれも RSA 鍵交換）。Encrypt-then-MAC に対応する。
- 対象外（理由コードで返す）: TLS 1.3、(EC)DHE（前方秘匿性があり、RSA の鍵では復号できない）、SSL 3.0、圧縮、再ネゴシエーション。
- 鍵・master secret・平文は観測として返すだけで、イベント台帳・監査ログ・Git には保存しない。ドライバの出力では、
  `factor` のような長いオプション値を digest に置き換える。

ドライバ側の変更（専門家が最後まで進めるために必要だったもの）:

- `view` intent: 登録済みの JPEG/PNG/GIF/WebP を、次のターンから Codex に添付する（最大 4 枚）。
- 非公開の候補チャネル: 専門家は `{"action":"candidate"}` で答えを Daybreak に渡す。値は `.metis-candidates/<run>/` の 0600
  ファイルにだけ置き、DB と監査ログには salt 付きの digest だけを残す。Daybreak は `metis agent candidates RUN` でファイルの
  パスを受け取り、値を見ずに `metis web submit --candidate-file` で提出する。
- 重複制御の範囲を attempt 単位にした。状態を持たない専門家は、他の担当が得た観測（`gcd` の結果など）を見られない。
  そのため次の wave の担当が先へ進めなかった。他の attempt が実行済みの要求は 1 回だけ再実行でき、同じ要求は run 全体で 8 回までとした。
  オプション変更や古い証拠による回避の拒否は、同じ attempt 内で引き続き効く。
- brief に前の wave の報告の要約（仮説、次の手、根拠のイベント番号）を載せる。
- ツールの検証エラーの理由を観測に含め、主要ツールの使い方をプロンプトに載せる。
- モデルサービス側の一時的な失敗は、同じターンを 1 回だけ再試行する。
- `--cyber-access-program` を明示的なオプションとして追加した（既定は指定しない）。

## 検証

- OpenSSL 3.5.7 が実際に生成したセッションで復号した（Python の ssl とメモリ BIO を使用。METIS とは独立した実装で暗号化）。
  - TLS 1.2: AES-128/256-CBC-SHA、AES-128/256-CBC-SHA256、AES-128/256-GCM。
  - TLS 1.0: AES-128-CBC-SHA。
  - 再開セッション: チケットによるものと session ID によるもの。
  - 全レコードの MAC・タグを検証し、平文が送信した HTTP と一致した。
- 誤った素因数、TLS 1.3、ECDHE はそれぞれ理由コードで返る。観測に秘密指数 d・p・q が含まれないことも確認した。
- ksnctf #33 の配布 PCAP（環境変数で指定、Git には入れない）: 4 セッション（うち再開 2）をすべて RC4-MD5 として復号し、MAC の失敗は 0。
  取り出した JPEG 本文は、PR #18 の時点で Daybreak が手作業で得たものと SHA-256 で一致した。

## 実 Codex による #33 の解析（回帰試験、practice 問題）

`metis web open` は `evaluation.split = practice` を返した（writeup がある）。独立評価ではない。

| 指標 | 値 |
| --- | --- |
| 専門家の起動（attempt） | 11（wave 2 つ、担当 8、retry 3） |
| Codex のターン | 52（一時エラーによるターンの再試行 5 を含む） |
| 拒否 | 重複 7（うち run 上限 3 を除けば正当な拒否） |
| 消費トークン | 467,340 入力 / 8,785 出力（担当ごとの最後の attempt の合計。それより前の attempt は含まないため下限値） |
| 実行時間 | 1,253 秒（最初から最後のログまで） |
| Daybreak の手動介入 | 解析・復号の作業は 0。オーケストレーション（plan 2、dispatch 6、retry 3、cancel 1）のみ |

到達点は次のとおり。

- 指示（note）なしで、専門家が `tls_certificates` → `gcd` → `tls_decrypt` → `tls_http_body`（derive）まで自分で進んだ。
  PR #18 の時点では、Daybreak が手作業で行っていた部分である。
- 最後の画像の閲覧と候補の受け渡しには至らなかった。復号結果（通信の平文と鍵の材料）がプロンプトに入った次の
  ターンで、Codex のサービスが「hardware key で再認証せよ」というエラーを返した。この失敗は 3 つの担当で再現し、
  `--isolation none`（隔離なし）でも、`--cyber-access-program daybreak_blue` を指定しても同じだった。METIS の隔離ではなく、
  アカウント側の認証要件と判断する。サービス側の安全上の関門なので回避は試みず、Issue #24 に記録した。
- 画像閲覧（`view`）と候補チャネル（`candidate`）は単体テストで検証済み。実 Codex での通しの検証は、再認証の後に行う。

## 残る作業

- マスターによる Codex の再認証（hardware key）の後に、`view` と `candidate` を含めて #33 を通しで再試行する。
- トークン消費は attempt ごとに上書きされている。attempt 単位で累積する記録は未実装。
