# 証跡の場所・フィールド・判断条件の棚卸し

主題が移っていることと、実際に調査できることを分けて確認します。以前の主題・ファイル単位の
棚卸しでは、具体的な保存先、カラム、イベント間の結合キーが落ちている箇所を見逃していました。
今回の修正では、一般的な注意事項に加え、実際に開く証跡と読む値を参照表に戻しています。

## 調査時にまず開く参照

| 調べたいこと | 具体的な手掛かり | 参照 |
| --- | --- | --- |
| 証拠を別の分析者が読み直せるか | 元の場所、取得後のパス、hash、レコード位置、フィールド、元の値、変換 | [証跡の指定方法](../skills/soc-triage/references/evidence-locators.md) |
| Windowsの実行・ログオン・設定 | ハイブとcontrol set、provider/channel/EventID、NewProcessId、LogonId、ProcessGuid | [Windows](../skills/soc-host-forensics/references/windows-artifacts.md) |
| Linuxの認証・実行・永続化 | journaldの時刻・boot、auditのtimestamp/serial、EXECVE/PATH、実際の設定所在 | [Linux](../skills/soc-host-forensics/references/linux-artifacts.md) |
| 稼働中のホスト | procfsのフィールド、CIMのプロセス・サービス列、ソケットとPIDの対応 | [ライブ収集](../skills/soc-remote-triage/references/live-collection-fields.md) |
| メモリ・バイナリ | process/address-space、VA/RVA/offset、symbols、形式と版の条件 | [ホスト](../skills/soc-host-forensics/SKILL.md)・[静的解析](../skills/soc-malware-triage/SKILL.md) |
| SIEM・センサーログ | index/table、元イベントと正規化フィールド、検索時刻、join、検索結果の上限 | [SIEM](../skills/soc-siem-hunt/SKILL.md) |
| AWS | CloudTrail格納階層、Records、identity/session、eventID、S3 bucket/key | [AWS](../skills/soc-cloud-identity-forensics/references/aws-cloudtrail.md) |
| ID・メール監査 | GraphとSigninLogsの列名差、変更プロパティ、M365/Oktaのイベントとセッション | [IDプロバイダー](../skills/soc-cloud-identity-forensics/references/entra-m365-okta.md) |
| GCP・Kubernetes | protoPayload、API audit stage/auditID、objectRef、workload UID、ログ保存設定 | [クラウド・クラスター](../skills/soc-cloud-identity-forensics/references/gcp-kubernetes.md) |
| PCAP・HTTP・DNS | packet/frame、方向、flow/transaction、欠損、受信側の結果 | [ネットワーク](../skills/soc-network-forensics/SKILL.md) |
| ブラウザー・メール | profile/DB、tablesとjoin、epoch、MIME part、繰り返すheaderの位置 | [ブラウザー](../skills/soc-browser-artifacts/SKILL.md)・[メール](../skills/soc-email-forensics/SKILL.md) |
| アーカイブ・構造化データ・Git | member ordinal/offset、具体的metadata、typed ID、JSON列、commit/tree/blob | [形式ごとのフィールド](../skills/soc-triage/references/container-and-structured-fields.md) |
| TIコンソール | first_submission_dateとlast_analysis_date、names、証明書の時刻と属性 | [インテリジェンス](../skills/soc-browser-console/references/intelligence-fields.md) |
| 検知・対応 | カード固有の収集元、フィールド、相関キー、成功の根拠、正常系と欠損 | [検知](../detections/README.md)・[対応手順](../playbooks/README.md) |

各SKILLから必要な参照だけを選びます。全表を毎回プロンプトへ貼る運用にはしません。
技術識別子は正しい綴りで保持し、説明と構成を独立して書き直します。

## 所在が変わる情報の扱い

製品の既定パスやフィールドは保持します。一方、組織ごとのindex alias、ユーザープロファイル、
マウント先、収集先、クラウドオブジェクトの実際のキーは、その案件で解決する必要があります。
参照表の例を実在する場所として使わず、取得manifestとschemaから確かめます。
取得できていない元パスはunknownのまま残し、ローカルコピーの名前で埋めません。

元の個別案件に属するホスト名、実証跡、答え、秘密や提供元固有のパスは共有技能へ移しません。
それは製品フィールドや一般的な証跡の所在を捨ててよいという意味ではありません。
現在調査している案件の実際の値とパスは、私有の証跡manifest・findingに保持します。

## 棚卸しの単位

[技術レビュー台帳](technical-retention.json)に、既存資料ごとの確認、見つかった欠落、補った
具体的な事実群、対応先、元資料のハッシュを記録します。元文章・元ファイル名・コードは格納しません。
[移行台帳](migration.json)は初期の対応関係と現在の知識ファイルhash、
[取り込み台帳](intake-ledger.json)は今回の独立原稿の検査・レビュー・反映を記録します。

資料の通読、技術項目の照合、機械的なhash/類似検査、合成問題での確認は別々の根拠です。
元ファイルの数やキーワード数を意味的な完全性の合格点にしません。元の全ケース本文や
全プログラム実装が同等に再現されたという主張もしません。

## 今後の取り込みで落としてはいけないもの

- 何を開くか：製品・形式・版、収集元、既定パスと実環境での解決方法。
- 何を読むか：table/column、provider/EventID、field/value、型、単位、epoch。
- 何と合わせるか：joinキー、host/tenant/boot/sessionの範囲、重複と欠損の扱い。
- 何まで言えるか：試行・受付・実行・効果を分け、正常系と追加証拠を示す。

これは内容レビューの必須観点です。既存の取り込み機は表現一致・識別語・形式・整合性を機械検査し、秘密・固有事例の不在は
内容レビューで確認します。この4項目の意味的な充足を自動証明するものではありません。
未対応のパーサーや未検証レイアウトは[解析能力](analyst-capabilities.md)と参照側へ明記します。

## 初回の具体性レビュー

4担当で既存119資料を再確認し、113資料を更新、6資料を理由付きで保持しました。
詳細参照15資料を加え、現在は21技能・38参照・検知61資料・対応手順12件・索引2件の計134資料です。
134資料それぞれに現在の内容hashと、作成者以外が確認したhashを結び付けています。
内容の追加・変更132件は、12回の取り込みで検査・内容確認・反映を行いました。

元の追跡ファイル1,735件をhashで照合しました。再分類すると、非空UTF-8テキスト1,502件と
空ファイル233件です。以前記載した1,629件は静的検索対象の選択数であり、読解可能なテキストの総数では
ありませんでした。静的走査は詳細レビュー箇所を探す補助であり、意味ごとに読了した件数ではありません。
初回に読解した元151ファイルの範囲を台帳の `source_review` に記録し、初期移行対象の知識113件を含みます。
全文確認と選択範囲の確認を台帳で区別し、個別案件の実データ・答え・独自schemaは共有知識へ転載しません。

改訂後の13参照を使う24問・55項目の[所在・フィールド評価](benchmark.md#technical-locator-regression)を
追加しました。問題から別担当が正解を独立導出し、型を含め55項目で一致を確認しています。
公開された合成問題であり、秘密の未見評価や全資料の理解保証ではありません。
Ollamaでは初回・時刻説明を補強した後の両方で23/24ケース・54/55項目でした。
Firefoxの起点年を観測日時の年と取り違える誤りが残り、評価は未合格として保存しています。
別担当の再採点でも一致しました。原値とschemaの確認を、モデルの回答だけで省略しないでください。
過去のモデル評価は当時の凍結本文に対する結果として残し、新本文の実証には転用しません。

## 追加の独立ダブルチェック

初回とは別に4担当で元資料とnative仕様を再照合したところ、さらに具体的な欠落と誤解釈が見つかりました。
21参照を10回の取り込み・35更新操作で補完しました。資料数は134件のままです。全資料の現行hashと
独立peerの確認hashを再結合し、過去の表の引用を現行の訂正済み内容へ更新しました。

Sysmonのイベント別 `Guid` / `GUID`、AWS KMSのCloudTrailとAPIのcasing、7-Zipの `ArcHistory`
の型、Androidの版別permission XML、ブラウザーの時刻・duration、OCI layerと履歴、LiME header、
Office/DEXの具体的な場所などを補いました。未知のschemaはnative候補名を残し、未検証と明記しています。

以前の151件に含まれなかった技術候補808件を、上限付き検索をやり直して確認しました。
確認範囲は全文・選択行・文字範囲・JSON schemaと説明欄を区別しています。検索に一致しなかった
非空543件は構造・静的分類のみで、意味レビュー済みではありません。原資料の全命題の同等性や
絶対的な欠落ゼロは主張しません。[追加レビュー](doublecheck-review.md)と[範囲台帳](doublecheck-review.json)に
候補の対応と未確定事項を記録しています。

追加18問を含む42ケース・103項目の評価を用意しました。追加問題のpeerは正解表を見た状態の
仕様照合であり、盲検ではありません。実測結果と凍結hashは[追加評価](benchmark.md#doublecheck-locator-regression)を参照してください。
取り込み機も、正当なDEX/JVMのinitializer名をHTMLと誤判定していた箇所を限定修正しました。
現行コードの全177テストが成功し、知識134資料の全体一致・長文一致は再検査で0件でした。

## 確定できない形式と残る条件

API Monitor保存物の[候補レイアウト](../skills/soc-malware-triage/references/api-monitor-candidate-layout.md)は、
失われていたmember名・offset候補も保持しています。ただし根拠は限られたparserと同じ前提の合成fixtureです。
実製品の版を識別する確かな条件や独立したnative exportとの照合がなく、一般的な形式仕様としては採用しません。
この条件を満たさない入力は未対応として扱います。バイナリEVTX、Registry、メモリなども外部readerが必要です。

前回は技能以外のコードも点検し、記録ヘルパーに直接継承された実装と固有事例コメントが残っていたことを確認しました。
独立実装へ置き換え、当時の全175テストと別担当の追加確認を通しました。METISのGit履歴にも同じ修正を適用済みで、
変更メッセージ・作者・日時・親子関係を保持しています。その処理でコミットIDが変わりました。元リポジトリは未変更です。
技術的な復元、表現一致検査、コードの由来検査を別々に扱います。詳細は[検証結果](verification.md)を参照してください。
