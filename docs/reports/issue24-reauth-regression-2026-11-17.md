# Issue #24: hardware-key 再認証後の KSNCTF #33 回帰（2026-11-17）

## 結果

Codex CLI 0.169.0 で、既存の KSNCTF #33 配布 PCAP を使ったオフライン解析を再実行した。hardware-key 再認証後に実 Codex ドライバが動作し、TLS 復号から画像閲覧、METIS の非公開候補チャネルへの引き渡しまで到達した。Codex 実行に認証エラーは出なかった。

これは METIS の driver/authentication 回帰と候補 handoff の証拠であり、KSNCTF の公式判定ではない。候補を公式サイトに提出しておらず、問題を公式に解いたとは主張しない。

## 実行範囲と証拠

- Run: `bbfb660443c4489c8120816a5b0caadf`。ネットワーク scope は空で、PCAP のローカル解析のみ。外部アクセスおよび提出は行っていない。
- 入力は既存の公開配布 PCAP（108,032 bytes、SHA-256 `a92c7853831392b5ff82f1e77fd83e6eeb113b269f949dcfda87618890f304b7`）。配布物自体は Git に追加していない。
- Codex CLI 0.169.0 の実 driver を delegated wave で起動し、独立 critic を含む全 assignment を完了後に synthesize した。全 Codex 実行が成功終了し、hardware-key 再認証エラーは観測しなかった。
- 専門家は PCAP の証明書から共有 RSA 素因数を得て、TLS 1.0 / RSA / RC4-MD5 セッションを復号した。記録済みの観測では全レコードの MAC が検証されている。
- 復号したサーバー本文から JPEG 2 枚を登録し、`view` で双方を確認した後、専門家が非公開 `candidate` チャネルに候補を渡した。候補値はこのレポート、通常イベント、Git に含めていない。
- 波の synthesize は全 3 assignment の報告を受理した。独立 critic は「2 枚が補完的であるだけでは全応答を確認した証明にならない」として完全性を inconclusive とし、復号 HTTP メッセージ一覧と画像境界・順序の Daybreak 確認を求めた。
- その指摘を受け、同じ登録 PCAP に対して `tls_certificates` と `tls_decrypt` の実装をローカルで再実行し、復号内容を出力せずにメタデータだけ監査した。4 接続すべて TLS 1.0 / RSA / RC4-MD5 として復号され、サーバー側 MAC 検証は接続別に 5/5、3/3、6/6、3/3 レコード成功。HTTP サーバー本文は接続 0 の JPEG (39,594 bytes)、接続 1 の HTML (283 bytes)、接続 2 の JPEG (50,439 bytes)、接続 3 の HTML (279 bytes) の計 4 件だった。追加の画像・テキスト本文は見つからなかった。
- 2 つの JPEG の SHA-256 は、専門家が `view` した登録済み derived artifact の内容とそれぞれ一致した。監査では本文、OCR、candidate を読み出していない。

## 判定と残作業

Issue #24 の狭い受け入れ条件である「再認証後に実 Codex で #33 の `view` と非公開 `candidate` handoff まで通る」は、ローカル回帰として達成した。外部認証要件の以前の障害は再現しなかった。critic が求めた全 HTTP 応答一覧も確認でき、他に画像・テキスト本文はなかった。

公式 verifier での提出・判定は未実施。画像上の文字列の境界・順序は、候補値を開かず、既存の専門家 `view` 観測に基づく。よってこの記録を公式 solve や solver の自律完遂の根拠には使わない。
