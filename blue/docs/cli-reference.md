# CLIリファレンス

リポジトリのルートから、Python 3.9以降で実行します。実行環境はmacOS/Linuxです。
ここではコマンドの使い分けと状態の読み方を説明します。接続先・証拠形式・取り込みの
詳細条件は、各節から専用仕様へ進んでください。

```sh
cd ~/Downloads/metis
metis blue --help
metis blue run --help
```

## 最初に動作を確認する

次の例は外部モデルや調査対象へ接続しません。`doctor`はPython・skills数・CLIの所在・
ワーカー上限を表示します。モデル認証やサービス接続の成功までは確認しません。

```sh
metis blue doctor
metis blue --db .state/demo/state.sqlite3 run '合成データで並列処理を確認' \
  --provider mock --plan examples/offline-plan.json --workers 2
```

`mock`は3タスクの依存関係とスケジューラーを試すためのものです。分析結果やモデルの
使用量を測定したことにはなりません。出力の`run`と`report`を控えます。同じコマンドを
再実行すると新しいrunが作成されます。

以下の`RUN_ID`、`TASK_ID`、`GRANT_ID`は、実際の出力で置き換える記号です。
`--db`は主CLIの共通引数なので、サブコマンドより前に置きます。

```sh
metis blue --db .state/demo/state.sqlite3 status RUN_ID
metis blue --db .state/demo/state.sqlite3 report RUN_ID
```

## 計画とワーカーを動かす

| コマンド | 処理 | 主な引数・注意点 |
| --- | --- | --- |
| `run OBJECTIVE` | runを作成し、計画・並列実行・報告を進める | `--plan`なし・実providerならモデルへ計画を依頼。実モデルでは最後にオーナーの報告も生成 |
| `prepare OBJECTIVE` | runとタスクを用意して実行前に止める | ネイティブエージェントから`claim`するための入口。`--plan`なし・実providerでは計画生成のモデル呼び出しがある |
| `resume RUN_ID` | 既存runの実行可能な`pending`タスクをプールへ戻す | 新しい計画を作らず、完了・失敗タスクを再実行しない。オーナーの最終報告生成も再実行しない |
| `claim RUN_ID` | 実行可能な1タスクと必要資源を一括確保する | 出力はタスクJSON、割当可能なものがなければ`null`。モデル起動やエージェント作成はしない |
| `finish RUN_ID TASK_ID` | 実行中タスクへ結果を登録し、占有を解放する | `--result-file`必須。`--state done`が既定。`failed`・`blocked`・`cancelled`も指定可能 |
| `close RUN_ID` | runの最終状態を決めて報告を保存する | `pending`・`running`が残る場合は拒否。全タスク`done`なら`completed`、それ以外は`needs-attention` |

`run`・`prepare`・`resume`の共通設定は次のとおりです。

| 設定 | 既定・優先順位 |
| --- | --- |
| `--provider` | `codex`。`claude`・`mock`も指定可能。通常のワーカープールに`ollama` providerはない |
| `--model` | 未指定なら利用するCLI側の既定モデル。METISは別世代のモデルへ自動変更しない |
| `--workers` | 指定時はその値も上限に加える。実ワーカー数はCPU数、provider上限、指定値の最小値 |
| `--provider-limit` | 正の明示値、次に`METIS_BLUE_PROVIDER_WORKERS`、最後に4。サービスの実際の残りquotaを検出する機能ではない |
| `--timeout` | モデルCLIの1呼び出しあたり240秒。run全体の期限ではない |
| `--plan` | `run`・`prepare`で使用。指定JSONが最優先。未指定かつ`mock`なら`examples/offline-plan.json`、それ以外はモデルが計画 |
| `--resources` | `run`・`prepare`で使用。既定は`examples/resources.json`で、`splunk`・`analysis-vm`・`browser-session`が各1枠 |

正の上限値を指定してください。メモリー容量・VM実数・SIEM検索可能数の自動検出は
ありません。リソース台帳は同じDBを使うrun間で共有されます。既存資源の容量を別の
値で再設定するには、後述の`capacity`を使います。

計画JSONは`tasks`配列を持ち、1〜128タスクを受け付けます。各タスクには、一意の`id`、
既存skill名の`skill`、空でない`prompt`が必要です。`depends_on`は先行タスクIDの配列、
`resources`は宣言済み資源名から正の必要数への対応です。依存循環・未知ID・未知skill・
容量を超える要求は拒否します。`mode`は省略または`read`だけです。

```json
{
  "tasks": [
    {
      "id": "review",
      "skill": "soc-triage",
      "prompt": "指定された合成証拠から、観測事実と不足証拠を分けて報告する。",
      "depends_on": [],
      "resources": {}
    }
  ]
}
```

実CLIを使う場合は、目的・許可範囲・証拠パスを計画に含めます。`--plan`を指定しても
ワーカーのモデル実行とオーナー報告は行われます。Claude CLIワーカーの標準ツールは
Read/Glob/Grep/WebFetch/WebSearchで、Bash・MCPを開放していません。バイナリ解析や
同梱パーサーの実行が必要なら、オーナーが許可された環境で前処理し、抽出結果を渡すか、
必要なツールがあるネイティブ環境を使います。[実行契約](runtime.md)を参照してください。

## ネイティブエージェントで担当を割り当てる

`prepare`と`claim`は、Codex/Claude側のエージェント起動機能と組み合わせます。
次の例ではモデル呼び出しを行わず、既存の合成計画だけを登録します。

```sh
metis blue --db .state/demo/state.sqlite3 prepare '担当割当の演習' \
  --provider mock --plan examples/offline-plan.json
metis blue --db .state/demo/state.sqlite3 claim RUN_ID
```

返されたタスクの`id`・目的・資源を担当者へ渡します。タスク割当の返却JSONには、取得
直前の状態値が含まれるため、現在の`running`状態は`status`で確認してください。
結果を私有ファイルへ保存し、担当処理と接続の停止を確認してから完了させます。

```sh
metis blue --db .state/demo/state.sqlite3 finish RUN_ID TASK_ID \
  --result-file .state/demo/result.txt --state done
```

この操作を次の実行可能タスクにも行い、全タスクが終端状態になってから`close`します。
`claim`の`null`は「割当できるタスクがない」という意味で、調査完了や証拠の陰性判定では
ありません。依存待ち・資源待ち・実行中・終端状態を`status`で区別してください。

状態遷移は次のように読みます。

| 対象 | 遷移・条件 |
| --- | --- |
| run | 作成時`pending` → 計画登録後`ready` → 割当後`running`。資源待ちなどが続けば`waiting`。完了時は`completed`または`needs-attention` |
| task | 作成時`pending` → `claim`で`running` → `finish`で`done` / `failed` / `blocked` / `cancelled` |
| 依存先が失敗したtask | 割当検査時に`pending`から`blocked`へ。成功した分析として扱わない |
| 資源lease | `claim`で必要な全資源を同時に取得。担当処理が停止し`finish`が成功した後に解放 |
| 接続consumer | 起動前に`starting`を登録し、その後`running` / `stopped`へ。`stopped`以外が残るtaskは`finish`できない |

プールは既定で約30秒、実行できるタスクがなく待ち続けた場合に`waiting`で戻ります。
古いワーカーや遠隔ジョブが停止したとは推定しません。中断後は`status`を調べ、実際の
停止を確認して処理します。`resume`に失敗タスクの再投入、停止不明接続の強制解除、
期限切れleaseの自動回収機能はありません。SIEMのジョブ再確認は専用の`reconcile`です。

## 資源容量・書き込み許可・接続

| コマンド | 意味 |
| --- | --- |
| `capacity RUN_ID RESOURCE UNITS` | 同じDB内で共有する資源容量を設定・変更する。既存leaseの使用数未満には縮小できない |
| `grant RUN_ID TASK_ID --resource RESOURCE --action ACTION --reason TEXT` | 既存のユーザー承認に基づく、対象・動作・タスクを限定した許可を発行する。既定`--ttl 300`秒・`--uses 1`回 |
| `connect PROFILE --action ACTION` | 実行予定を表示する。`--profiles`の既定は`.state/connections.json` |
| `connect PROFILE --action ACTION --execute --run RUN_ID --task TASK_ID` | leaseを持つ実行中タスクから接続する。書き込み扱いの動作には`--grant GRANT_ID`も必要 |

オーナー用能力値は`METIS_BLUE_OWNER_TOKEN`が設定されていれば優先し、なければDBと同じ
ディレクトリの`private/RUN_ID.owner`から読みます。この値をワーカーの会話へ渡さず、
オーナーがbrokerを操作します。`grant`コマンドは承認を新しく生み出すものではなく、
実際の承認範囲を記録する操作です。期限前でも回数を使い切ったgrantは再利用できません。

プレビュー例は調査対象へ接続しません。主CLIはDBを開くため、私有DBの初期化は行われる
場合があります。

```sh
metis blue --db .state/demo/state.sqlite3 connect evidence-host \
  --action system --profiles examples/connections.json
```

`connect --timeout`は既定60秒です。主CLIの接続実行は前面プロセスとして待ち、期限時に
プロセスグループを停止します。常駐セッションを使うPython API、クライアント導入、SSH鍵、
RDP証明書、VNCパスワード、VPNプロファイルは[接続仕様](connections.md)を参照してください。
`connect`自体に任意の遠隔シェルコマンドを渡す機能はありません。

## 状態・報告・トランスクリプト

| コマンド | 出力と副作用 |
| --- | --- |
| `status RUN_ID` | run・task・メッセージ・使用量・接続状態をJSONで表示。HTMLは生成しない |
| `report RUN_ID` | 現在のDB内容から`reports/RUN_ID.json`と`.html`を生成・更新。タスクを完了させたりモデルへ要約させたりしない |
| `view RUN_ID` | DBの報告を、認証用URLを持つ127.0.0.1限定サーバーで表示。`--port 0`が既定で空きポートを選ぶ。ブラウザーは自動起動しない |
| `import RUN_ID TASK_ID PATH --provider codex\|claude` | 明示したJSONLトランスクリプトからメッセージと提供元usageを取り込み、報告を更新。task状態は変更しない |

同じファイルパスの再取り込みは、そのsourceの観測を原子的に置き換えます。別名コピーや
親子の重複集計を自動判定する機能はないため、同じ推論ストリームを複数sourceから足さない
運用が必要です。`report`は既存記録の整形、`import`は記録の追加・更新です。

使用量の欠測は`null` / `unknown`、提供元が明示した0は0です。キャッシュ込みの
`input_total`をキャッシュ内訳へ再加算しません。全体の`totals`と、観測できた部分だけの
`known_subtotals`を区別し、`usage_coverage.total_complete`と内訳全体の`complete`を
確認します。旧DBの値は未検証の`legacy_usage`として保持します。[会計・移行仕様](runtime.md)
に詳しい条件があります。

主CLIの既定DBはMETIS直下の`.state/state.sqlite3`です。`--db`を変えると、ownerファイル、
報告、旧式benchmark出力もそのDBの親ディレクトリに置かれます。Git除外を保つため、
通常は`.state/`以下を使ってください。`doctor`と`--help`以外はDBを開き、必要に応じて
初期化や旧schemaの移行を行います。

## 別モジュールの解析・検索・取り込み

以下は`metis blue SUBCOMMAND`ではなく、別のモジュールを直接実行します。

| 入口 | 用途と主要条件 | 詳細 |
| --- | --- | --- |
| `metis evidence KIND INPUT --out PATH` | `email` / `browser` / `json` / `cloudtrail` / `evtx-xml`。既定16MiB・10,000レコード・15秒。METISの`.state/`内に新規JSONを出力 | [解析形式と上限](artifact-tools.md) |
| `metis siem search` | `--run`・`--task`・`--profile`・`--request`で限定検索（結果は標準出力）。実行中taskのSIEM leaseと読み取り資格情報が必要 | [SIEM仕様](siem-support.md) |
| `metis siem reconcile` | 同じrun/task/profileと`--connection-id`で、自分のSplunkジョブの終了状態を再確認 | [終了不明の扱い](siem-support.md) |
| `python3 -m metis.blue.runtime.knowledge_intake snapshot` / `diff` | `--source`を読み取り専用で調べ、hashの基準点・差分を記録。`diff`は`--baseline`も必要 | [取り込み仕様](knowledge-intake.md) |
| `python3 -m metis.blue.runtime.knowledge_intake check` / `apply` / `recover` / `audit-library` | 独立原稿の検査・レビュー後の反映・中断回復・既存知識の一致検査。`--source`と`--out`が必要 | [レビュー・反映条件](knowledge-intake.md) |
| `python3 -m metis.blue.runtime.knowledge_inventory --source SOURCE --out PATH` | ファイルと見出し等の構造を棚卸し。構造件数は意味の移行完了数ではない | [棚卸し](knowledge-intake.md) |

SIEMモジュールの既定プロファイルは`examples/siem.json`です。実運用の私有設定は
`--profiles .state/private/siem.json`で選びます。SIEMの`--db`はMETISの`.state/`内にある既存DBが
必要で、主CLIの任意DBパス指定と同じ制約ではありません。資格情報はprofileの`token_env`
が指す環境変数から読みます。取り込み・棚卸しの出力先は`.state/intake/`内のJSONです。
これらの出力先は主CLIの`--db`では変わりません。

## 評価用CLIを使い分ける

| 入口 | 実行内容 |
| --- | --- |
| `python3 -m metis.blue.runtime.readiness_eval bundle` | `--cases`の設問と必要参照から、正解値を含まないプロンプトとhash付きメタデータを作る。モデルは呼ばない |
| `python3 -m metis.blue.runtime.readiness_eval score` | `--answer`を`--bundle-meta`の凍結条件で厳密採点。`--provider desktop\|ollama`と`--model`は識別記録でありモデル起動指示ではない |
| `python3 -m metis.blue.runtime.readiness_eval run-ollama` | 凍結bundleを実際のOllamaへ1回送って保存・採点する。`--model`は導入済みの正確なタグ、`--num-ctx`は必須で65,536以上、既定`--timeout 600`秒・`--num-predict 4096` |
| `metis blue benchmark` | 旧4ケースの比較。既定providerは`claude`。`--provider ollama --models ...`でOllama比較も可能 |
| `python3 -m metis.blue.runtime.skill_eval --provider claude\|ollama --model MODEL` | 旧2バンドル・9項目のskill参照付き評価。既定`--timeout 180`秒 |

現在の24ケース評価を準備する例です。これはローカルファイル作成だけを行います。

```sh
python3 -m metis.blue.runtime.readiness_eval bundle --protocol v2 \
  --cases examples/readiness-cases-v2.json \
  --out .state/benchmarks/tutorial-v2.prompt.txt
```

`bundle`の既定は`--protocol v1`・`examples/readiness-cases.json`です。v2は末尾の出力・
ツール禁止契約を追加します。評価済みbundleの条件を変えて使い回さず、別の出力名で作成
してください。モデルへ渡すのは生成された`.prompt.txt`だけで、正解を含むcase JSONでは
ありません。出力は`.state/benchmarks/`に置きます。

旧`benchmark`の既定は、1モデル呼び出し180秒・Ollama反復1回・生成上限4,096です。
`--think default`はモデル既定を使い、`--protocol bundled-v1`が既定です。Ollamaでは
`--models`が必要で、Claudeでモデルを省略すると`claude-opus-4-6`と`claude-opus-4-8`を比較対象にします。
Desktopの起動・UI操作はこれらのコマンドが自動で行うものではありません。
採点・可視ツール挙動・モデル表示・使用量の扱いは[評価仕様](benchmark.md)と
[版付き比較仕様](readiness-protocols.md)を参照してください。

## 環境変数と設定ファイル

| 名前 | 用途・優先順位 |
| --- | --- |
| `METIS_BLUE_CODEX_BIN` / `METIS_BLUE_CLAUDE_BIN` | モデルCLI実行ファイルを明示。次にPATHを探し、その後に対応するアプリ同梱の候補を探す。指定したパスが存在しなければ失敗する |
| `METIS_BLUE_PROVIDER_WORKERS` | `--provider-limit`がない場合のprovider並列上限。未設定は4 |
| `METIS_BLUE_OWNER_TOKEN` | ownerファイルより優先するオーナー能力値。runごとの値を使う |
| `METIS_BLUE_OLLAMA_URL` / `OLLAMA_HOST` | Ollama接続先は`--url`、`METIS_BLUE_OLLAMA_URL`、`OLLAMA_HOST`、`http://127.0.0.1:11434`の順。資格情報・パス・queryを含まないHTTP(S) originを指定 |
| profileの`password_env` / `token_env` | 明示した環境変数から接続資格情報を読む。設定ファイルには変数名を置く |
| `METIS_DENY_PATTERN` | 元資料の識別語をリポジトリ外から渡す正規表現。取り込み`check`・`apply`で必要。監査でも使用 |
| `SOCLOG_ROOT` | 次節のケースノート保存先。未設定はMETIS直下の`logs/`。主CLIの`--db`とは独立 |

CLIへのログインとDesktopアプリへのログインは別です。`doctor`で実行ファイルが見つかっても
モデル呼び出しの認証成功は保証しません。

## 調査ノートを記録するsoclog

`metis journal`はアナリストのケースノート用です。run/task/leaseを持つSQLite
とは別の保存系で、自動同期・自動取り込みは行いません。`run_id`と`case_id`も別のIDです。
同じ調査では対応関係をノートへ記録してください。

| サブコマンド | 記録するもの |
| --- | --- |
| `open --case SLUG` | ケースディレクトリを作成。既定`--type incident`。実際のcase IDは出力から確認 |
| `note --case CASE_ID --text TEXT` | 時系列の分析メモ。既定`--phase analysis` |
| `query --case CASE_ID --platform NAME --query TEXT` | 実施した検索と目的・結果件数を記録。クエリーそのものは実行しない。未判明の`--hits`は既定-1 |
| `finding --case CASE_ID --summary TEXT --evidence LOCATOR` | 根拠付き所見。`--evidence`必須、既定`--confidence medium` |
| `lesson --case CASE_ID --text TEXT` | ケース内の学び。記録しただけでskillsやGitへ昇格しない |
| `close --case CASE_ID --outcome OUTCOME` | ケースノートを結論付きで閉じる。SQLiteのrunは閉じない |
| `show --case CASE_ID` / `index` / `lessons` | ケース表示・私有索引の再生成・ケース横断の学びの表示 |

```sh
metis journal open --case cli-practice --type training \
  --title 'CLI操作の演習' --objective '提供済み合成証拠の観測範囲を記録する'
metis journal finding --case CASE_ID \
  --summary '提供された合成ファイルを確認した' \
  --evidence 'examples/alert.json（演習用データ）' --confidence high
metis journal close --case CASE_ID --outcome inconclusive \
  --summary '外部の収集・解析は行っていない'
```

ケースには`case.md`、`timeline.jsonl`、`queries.jsonl`、`findings.jsonl`、`lessons.md`と
作業用ディレクトリが作られます。`logs/`はGit対象外です。秘密値を含む記録はscreeningで
拒否される場合があります。全文の自由記述が安全に共有できるという意味ではありません。

## 終了コードと、つまずきやすい状態

主CLIは通常0、入力・権限・処理エラーは2、中断を主CLIが受けた場合は130です。
`run`はrunが`completed`以外なら2を返します。一方、`resume`や`close`はコマンド処理が
成功すれば、runが`waiting`や`needs-attention`でも0になる場合があります。終了コードと
`status`内のrun/task状態を合わせて確認してください。

- `claim`が`null`：依存先・占有枠・残タスクを確認する。完了とは限らない。
- `Task is not running`：未割当または既に完了したタスク。`status`を照合する。
- `Stop active connections ...`：consumerの停止を先に確認する。枠だけ解放しない。
- `Provider ...` / CLI認証エラー：実行ファイル・CLIログイン・指定モデルを確認する。
- 解析CLIの終了2：`complete_for_input`と`limitations`を読み、部分結果を陰性と扱わない。
- SIEMの終了2：返却上限・部分失敗・consumer終了不明などを仕様に沿って確認する。
- 取り込みの終了2：原稿・hash・禁止語設定・レビュー・中断回復を確認し、ゲートを飛ばさない。

開発用の全試験は`.venv/bin/pytest tests/blue`、構造検査は
`python3 scripts/check_repo.py`です。接続サーバーを構築する`python3 scripts/connection_lab.py`
はDockerと接続クライアントを使う別の統合試験で、オフラインの操作説明とは分けています。
検証済みの範囲は[検証結果](verification.md)を参照してください。
