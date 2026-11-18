# SIEM対応状況

METISにはSplunkとElasticsearchの限定された読み取りAPIアダプターがあります。
接続先・index・fieldをオーナーが指定し、絶対UTC範囲と単純な等値条件を渡します。
任意のSPL、Query DSL、スクリプト、保存検索、検知ルール配備はこのインタフェースに渡せません。
APIが使えない場合は、接続済みブラウザーかエクスポート済み証拠へ切り替えます。

| 対象 | 利用できる機能 | 検証範囲 |
| --- | --- | --- |
| Splunk | 検索ジョブ作成、終了状態確認、v2 resultsのページ取得、取消、同じジョブの再確認 | localhost試験に加え、実Splunk Enterprise 10.4.3で合成データ7件・上限3件・0件を検証 |
| Elasticsearch | indexを限定したterm/range検索、取得行数・時間・返却fieldの上限、部分結果判定 | 自作localhostサーバーで検証。実製品・バージョン・mappingとの適合は別途必要 |
| Sentinel / Defender XDR | Kusto KQLと証拠分析の技能 | 専用APIアダプターなし。テーブル・テナント・権限を確認 |
| OpenSearch | 調査の共通知識 | ElasticsearchとのAPI・クエリー互換性を未認定 |
| Wazuh | アラート・ルール・fieldの分析 | UIまたは提供済みログ。専用APIなし |
| Zeek / Suricata | ネットワークログの分析 | ローカル証拠を利用。SIEMサービス自体ではない |
| その他のSIEM | 汎用の証拠評価と調査計画 | 製品固有接続は追加作業 |

モデル評価やRDP/VPN接続の成功を、SIEM実製品の動作確認へ流用しません。
検知精度・誤検知率・検索言語全体の対応も、このアダプターの合格範囲に含めません。

## 接続前の準備

[接続プロファイル例](../examples/siem.json)を .state/private/siem.json に用意します。
認証情報はファイルのtoken_envが指定する環境変数へ設定し、値を設定ファイルや引数へ
書きません。SplunkはBearerトークン、またはauth_schemeをSplunkにしたsessionKeyを
受け付けます。ElasticsearchはBearerまたはApiKeyです。認証・権限の方式は
[Splunk認証の公式説明](https://help.splunk.com/en/splunk-enterprise/leverage-rest-apis/rest-api-user-manual/9.4/rest-api-user-manual/basic-concepts-about-the-splunk-platform-rest-api)
と実環境の設定を照合してください。

通常はHTTPSを必須とし、証明書とhostnameを検証します。組織内CAを使う場合は
ca_fileに信頼するCAファイルを明示します。自己署名でも接続先を含むSANが必要です。
リダイレクト・環境変数のHTTPプロキシ・Cookieは利用しません。接続先への認証情報が
別のホストへ送られないための制限です。HTTPの例外はtest_only_httpを明示した
127.0.0.1等のループバックIPに限ります。localhostというホスト名では有効にできません。

オーナーはSIEMごとの同時検索枠を宣言し、Storeでtaskへleaseを付けてから呼び出します。
標準の[リソース設定](../examples/resources.json)はsplunkを1枠に制限します。
Elastic用のresourceも別途設定してください。外部ツールで直接開始する検索は
この制御の対象外なので、同じ枠を使う運用を揃える必要があります。

## 検索入力

入力は次の6項目です。追加の項目やクエリー文字列は拒否します。

~~~json
{
  "index": "security_events",
  "start": "2026-01-01T00:00:00Z",
  "end": "2026-01-01T00:10:00Z",
  "filters": {"host": "asset-7"},
  "fields": ["_time", "host", "EventCode"],
  "limit": 100
}
~~~

開始は含み、終了は含まないUTC範囲を使います。indexとfieldはプロファイルの許可一覧から
選びます。等値条件は短い文字列だけに限定し、ワイルドカードや検索演算子を受け付けません。
SplunkとElasticsearchで大小文字、型、keywordのmapping等が同じ意味になるとは限りません。
事前に既知データと照合し、件数の解釈へ検索仕様を添えてください。

デフォルトは1時間以内・1,000行・30秒です。オーナーのプロファイルでも時間幅は24時間、
返却行数は5,000行、検索時間は120秒を超えられません。HTTP応答は1回2 MiBまでです。
Elasticsearchは1回のbounded searchに限定し、上限を超える母集団を全件取得したと扱いません。
巨大な検索を細かい検索へ勝手に分割して、予算・lease制限を迂回しないでください。

オーナー（METIS では Daybreak）が `metis lease task RUN TASK splunk=1` で枠を貸したtaskから呼び出します。
検索後は `metis lease finish RUN TASK` で枠を返します（停止を確認できない接続があると拒否されます）。

~~~bash
metis siem search --run "$RUN" --task "$TASK" --profiles .state/private/siem.json --profile splunk-read --request .state/private/query.json
~~~

Pythonからは`metis.blue.siem.execute(ledger, run, task, profile, request)`（`ledger`は`metis.blue.ledger.ConnectionLedger`）で利用できます。
出力にはrows、reported_total、returned、complete、reasons、consumer_stopped、
リクエストと応答のハッシュを含めます。返却内容は秘密値をマスクした分析用派生物です。
原本と同一の証拠として扱わず、必要な原本は別の承認済み取得経路で保全してください。
メッセージ台帳には件数・状態・ハッシュを記録し、検索文や取得行を記録しません。

## 空結果、部分結果、終了不明

completeは「指定条件・取得範囲について、検出した上限や部分失敗がない」という結果です。
収集されていないログの不存在や、環境全体に侵害がないことの証明にはなりません。

SplunkはDONE状態と終了フラグを確認し、finalized、警告、結果上限、ページ不足やoffsetの
不整合を部分結果として扱います。ジョブと結果APIの役割は
[公式検索API仕様](https://help.splunk.com/en/splunk-cloud-platform/leverage-rest-apis/rest-api-reference/9.3.2408/search-endpoints/search-endpoint-descriptions)
に基づきます。Elasticsearchではtimed_out、terminated_early、失敗・不足shard、
下限にすぎないtotal、取得上限を確認します。
[Search API仕様](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/search-search.html)
の返却項目を、単なるHTTP成功だけで置き換えないでください。

通信断、認証エラー、不明なJSON、ジョブ作成応答の消失では、サーバー側検索の終了を
断定できない場合があります。その場合はconsumerをrunningのまま残し、`ConnectionLedger.finish_task`（`metis lease finish`）が
leaseを解放しないようにします。取消APIの成功応答だけでも終了扱いにせず、終了状態を
再確認します。Splunkでは保存した自分のジョブIDだけを次の経路で再確認できます。

~~~bash
metis siem reconcile --run "$RUN" --task "$TASK" --profiles .state/private/siem.json --profile splunk-read --connection-id "$CONNECTION"
~~~

プロファイルやtaskが異なる再確認は拒否します。プロセス中断時もconnectionと操作IDは
私有SQLiteに残ります。Elasticsearchの同期検索には再確認用ジョブIDがないため、終了不明を
自動解放する経路はありません。オーナーが実製品側で該当処理の終了と残りの消費者を確認し、
根拠をケースへ記録してから運用上の回復を行います。時間経過だけで枠を返してはいけません。

## 検証手順

~~~bash
python3 -m unittest discover -s tests -p 'test_siem.py' -v
~~~

このテストは自作のHTTPサーバーをlocalhostに起動します。ページング、空結果、部分結果、
タイムアウト、取消後の状態確認、終了不明時の枠保持、別taskとの競合、秘密値のマスク、
redirect/proxy拒否、応答上限を試します。実SplunkやElasticsearchの合格とは表示しません。

Splunk Enterprise 10.4.3の使い捨て環境でも、検索権限だけを持つreader、sessionKey、
明示CAとhostname検証を使って確認しました。7件をpage_size=2で取得でき、7件の原イベントが
重複せず返りました。limit=3では3件を返しつつpartial、存在しない合成ホストでは0件の
completeになりました。処理中ジョブの取消と、その後のジョブ消失も確認しました。
各実行後にconsumerとleaseが残らないことを確認しています。

この実製品試験で、PARSING状態にはresultCountがまだないことを確認し、非終了状態では
件数を要求せず待ち、DONEでは必須にする修正を加えました。実行記録は私有の
.state/siem-lab/real-product-validation.jsonに保存します。実製品での長時間負荷、分散検索の
部分障害、全認証方式、他バージョン、Elasticsearch実製品はこの確認に含まれません。

本番へ接続する前に、別途次を検証します。

1. 読み取り用権限と対象indexを限定し、検索枠・バージョン・証明書・認証方式を記録する。
2. 専用の合成データに既知件数、異なるUTC時刻、重複、期待するfieldを用意する。
3. アダプターの結果と製品側の同じ母集団を照合し、時刻の境界・型・大小文字を確認する。
4. 空結果、行数上限、複数ページ、拒否された検索、途中停止、再確認後のlease解放を確認する。
5. 実行証拠と製品の版を .state/ 配下へ保存し、成功した条件と未検証条件を報告する。

保存検索・検知ルールの配備、ログ投入、封じ込め、アカウント変更は読み取り検索と分け、
ユーザーの許可または適用範囲内のオーナーgrantで行ってください。
