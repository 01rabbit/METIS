# プロAI Blue Team Agent METIS Blue
> このディレクトリは METIS Blue（SOC 調査向けの Blue Team 機能）の技能・検知資料・対応手順・文書・評価資料です。
> コマンドは METIS のチェックアウト直下から `metis blue`、`metis journal`、`metis evidence`、`metis siem` で実行します。
> 私有の実行状態は `blue/.state/`（Git 対象外）に置きます。METIS 側の使い方は [docs/BLUE_TEAM.md](../docs/BLUE_TEAM.md) を参照してください。


> 証拠を確かめ、判断を支え、次の一手まで。

はじめまして、**METIS Blue**です。アラートの初動から、ログ・ホスト・ネットワークの調査、検知の改善、インシデントの引き継ぎまでを手伝う、SOCのAI Blue Team Agentです。

「このアラート、何から調べればいい？」「ログの見方が合っているか確認したい」「次の担当者に根拠付きで渡したい」。そんなときに呼んでください。Tier 1の判断を支え、Tier 2/3で必要になる仮説検証、影響範囲の特定、根本原因の分析を進めます。

依頼の窓口はぼく一人。独立して調べられることは専門ワーカーへ配り、証拠と結論を照合してお返しします。分からないことは埋め合わせず、**何が分かったか・何が未確定か・次に何を確かめるか**を整理するのが仕事です。

| プロフィール | 内容 |
| --- | --- |
| 名前 | METIS Blue／リポジトリ名は `metis` |
| 職種 | プロAI Blue Team Agent／SOC調査・対応支援 |
| 得意な仕事 | 初動整理、証拠の突き合わせ、調査の分担、検知の見直し、根拠付きの引き継ぎ |
| 仕事の姿勢 | 原本と根拠を大切にする。仮説と事実を分ける。証拠不足も結果として伝える |
| チーム編成 | 一人のオーナーと、環境の上限に合わせて動く専門ワーカー |
| 知識の道具箱 | BlueTeamSkills 21技能・38参照、検知61資料、対応手順12件 |
| 約束 | 重い検索は枠を確保してから。外部への変更は許可の範囲内で。秘密情報と調査記録は私有領域へ |

ぼくが担うのは、証拠・権限・対応形式を明示したSOC調査支援です。調査担当者と一緒に使うことを前提とし、任意の事案を自律解決するTier 3認証や、すべての証拠形式への対応をうたうものではありません。

---

## 利用仕様

以下は現在の実装に基づく仕様です。詳細は[ドキュメント一覧](docs/README.md)、コマンドは[CLIリファレンス](docs/cli-reference.md)、仕組みは[アーキテクチャ](docs/architecture.md)を参照してください。

### 1. 動作環境と利用モード

基本環境は **Python 3.9以降・macOSまたはLinux** です。Pythonの本体機能に追加パッケージは不要です。ネイティブWindowsではWSLを使用してください。モデル、接続クライアント、専門解析ツールは用途に応じて別途用意します。

| 利用モード | 入口とできること | 必要なもの・制約 |
| --- | --- | --- |
| アプリ内のネイティブ運用 | CodexまたはClaude DesktopのCodeモードでフォルダーを開く。主エージェントが調査・画面操作・ネイティブワーカーを統括 | ホスト環境の認証、利用可能なツール、権限。会話・使用量は取得できる明示的なtranscriptから取り込む |
| CLI運用 | `metis blue run` が計画・読み取り分析の並列実行・最終統合を行う | 認証済みCodex CLIまたはClaude Code CLI。ClaudeワーカーはRead/Glob/Grep/WebFetch/WebSearch、Codexワーカーはread-only sandbox |
| オフライン動作確認 | `--provider mock` でキュー、依存関係、状態遷移、報告を確認 | モデル認証不要。実分析や実測トークンを生成したことにはしない |
| Ollama評価 | 指定したサーバーのインストール済みモデルで合成課題を評価 | 到達可能なOllama。現行は評価専用で、`metis run` のワーカーproviderには使えない |

Claude DesktopのログインとCLIの認証は別です。CLIがPATHにない場合は `METIS_BLUE_CODEX_BIN` / `METIS_BLUE_CLAUDE_BIN` で実行ファイルを指定できます。モデル名は明示指定でき、自動で別世代へ置き換えません。

### 2. 最初の起動

```bash
cd ~/Downloads/metis
metis blue doctor
metis blue run '合成証拠の並列解析デモ' --provider mock --workers 3
```

`doctor` はPython、技能数、ワーカー数、CLIの場所を確認します。認証成功や接続先の動作を検証するコマンドではありません。デモは同梱の合成証拠・計画を使い、終了時に実行IDとレポートの場所を表示します。

アプリ内では、フォルダーを開いて次のように依頼できます。

> METIS Blue、examples/alert.json を調べて。独立した証拠分析を並列化し、確定事項・未確定事項・追加収集すべき証拠を、Tier 1向けに日本語でまとめて。

認証済みCLIから実モデルを使う場合：

```bash
metis blue run 'examples/alert.json を調査して日本語で報告' \
  --provider codex --plan examples/offline-plan.json --workers 3

metis blue run 'examples/alert.json を調査して日本語で報告' \
  --provider claude --model claude-opus-4-6 \
  --plan examples/offline-plan.json --workers 3
```

`--plan` は既存の調査計画を読み込み、モデルへの計画作成依頼を省きます。実モデルで省略するとオーナーが計画を作成します。実際の調査では、証拠の場所、対象資産、期間、求める判断、検索やVMの上限、既存の変更許可を依頼に添えてください。

### 3. 提供機能と対応範囲

| 機能 | 現在できること | 詳細仕様 |
| --- | --- | --- |
| オーナーとワーカープール | 単一窓口、依存関係のある計画、空き枠への追加配分、失敗の伝播、再開 | [設計](docs/architecture.md)・[実行モデル](docs/runtime.md) |
| BlueTeamSkills | 初動、ホスト、メモリ、ネットワーク、メール、保存ブラウザー証拠、クラウドID、静的マルウェア調査、検知、報告、防御演習 | [技能と準備状況](docs/skill-readiness.md)・[専門能力の対応表](docs/analyst-capabilities.md) |
| オフライン解析 | EML/MBOX、対応するChromium/Firefox履歴、厳密JSON、CloudTrail JSON、EVTXのXML出力 | [入力形式・上限・出力](docs/artifact-tools.md) |
| SIEM | Splunkのジョブ管理・ページ取得、Elasticsearchの限定検索。範囲・行数・時間・検索枠を制御 | [SIEM対応状況](docs/siem-support.md) |
| 接続 | SSH / RDP / VNC / SOCKS / VPNのプロファイルとプロセス管理。ブラウザーはURLと操作契約をホスト環境へ渡す | [接続仕様](docs/connections.md) |
| 権限と占有管理 | 複数リソースの一括予約、タスク・操作・期限・回数を限定した変更許可 | [実行モデル](docs/runtime.md) |
| 調査・実行の記録 | ケース記録、メッセージ、状態、エージェント別の使用量、HTML/JSON報告、loopbackビューワー | [記録の構成](docs/architecture.md)・[CLI](docs/cli-reference.md) |
| 継続的な知識更新 | ハッシュによる変更検知、独立原稿の検査・レビュー・反映、中断時の回復 | [取り込み仕様](docs/knowledge-intake.md) |
| 評価・監査 | 合成課題、参照本文を使う評価、厳密な採点、移行先・Git履歴の検査 | [評価仕様](docs/benchmark.md)・[知識監査](docs/knowledge-audit.md) |

バイナリEVTX、メモリ画像、PCAP等の本格的な解析には対応する外部ツールが必要です。Sentinel / Defender XDR等には調査知識がありますが、専用APIアダプターは同梱していません。RDP等はネイティブクライアントをMETISが管理する構成で、クライアント本体の自動インストールは行いません。

### 4. 並列数・共有リソース・変更権限

CLIのワーカー数はCPU数、指定数、申告したprovider上限の最小値です。provider上限は `--provider-limit`、または `METIS_BLUE_PROVIDER_WORKERS` で指定し、未指定なら4です。契約上の同時実行枠をモデル名から自動推定しません。

[標準リソース設定](examples/resources.json)は、Splunk、分析VM、ブラウザーセッションを各1枠にしています。実環境の設定は `--resources` で渡します。同じSQLiteを使う実行間で枠を共有し、必要な枠をまとめて確保できたタスクから動かします。別DBやMETISを経由しない操作は、この調停の対象外です。

| 操作 | 扱い |
| --- | --- |
| 許可範囲内の閲覧・認証・証拠分析 | 調査として実施。ケース内の作業・記録も含む |
| 提出、封じ込め、設定・アカウント・検知ルールの変更等 | ユーザーの承認、またはその承認に基づくオーナーの事前grantが必要 |
| 書き込みを伴い得る対話型リモート操作、VPN等の起動 | 接続仕様に従い、該当操作のgrantとリソース枠を確認 |
| 権限不足・追加リソースが必要 | ワーカーからオーナーへ報告し、配分・許可を見直す |

`connect` は既定で接続計画を表示し、`--execute` を付けた場合だけ起動します。接続中やリモート処理の終了が不明な間は、タスク完了・枠の解放を行いません。経過時間だけで終了扱いにせず、実際の処理を確認してから復旧します。

CLI分析ワーカーには読み取り用の制約があります。ブラウザー、MCP、外部ツールまで含む任意の操作をSQLiteだけで隔離する仕組みではないため、接続先の読み取り権限やホスト環境の制御も併用します。

### 5. 結果の確認・使用量・保存先

以下の `RUN_ID` は起動時に表示された実行IDへ置き換えます。

```bash
metis blue status RUN_ID
metis blue report RUN_ID
metis blue view RUN_ID
```

報告では、証拠の場所・時刻・観測事実、仮説と確度、調査範囲、失敗・不足した証拠、次の対応を区別します。ビューワーはloopback限定で、ランダムなアクセスキーを使います。

標準設定の保存先は次のとおりです。DBを変更すると、その親ディレクトリが実行レポートとオーナー情報の基準になります。

| 保存先 | 用途 |
| --- | --- |
| `.state/state.sqlite3` | 実行・タスク・リソース・接続・メッセージ・使用量 |
| `.state/reports/<RUN_ID>.json` / `.html` | 集約した実行レポート |
| `.state/private/` | オーナー情報等。SIEMの秘密情報は参照先を指定 |
| `.state/connections.json` | 利用者が作成する接続プロファイル |
| `.state/benchmarks/` / `.state/intake/` | 評価記録・取り込みの私有作業領域 |
| `.metis-state/journal/<CASE_ID>/` | `metis journal` による証拠・時系列・所見のケース記録 |

`RUN_ID` とケース記録の `CASE_ID` は別の識別子です。ネイティブ会話を集計する場合は、対象セッションのtranscriptを明示して `metis import` で取り込みます。同じファイルの再取り込みは置き換えで、親の集約値と子の使用量を重ねて計上しない運用が必要です。

使用量は実測値を使い、未取得は `null` / `unknown` として保持します。完全な合計と取得済み小計を区別し、UIのコンテキスト量や文字数からトークン数を推定しません。旧SQLiteの数値は保存しますが、過去の0補完と実測値を判別できないため、移行後の実測合計から除外します。[会計・移行仕様](docs/runtime.md)に詳細を記載しています。

**`.state/` と `.metis-state/` はGit対象外**です。秘密情報を会話や引数へ書かず、承認された参照経路で渡してください。別のcloneでも `git config core.hooksPath .githooks` を設定すると、同梱のpre-commit検査を使えます。

### 6. 知識の構成と更新

技能の正本は `skills/` です。Codexの `.agents/skills/`、Claudeの `.claude/skills/` は同じ正本を参照します。運用契約は [AGENTS.md](AGENTS.md)、Claudeの入口は [CLAUDE.md](CLAUDE.md) です。必要な技能・参照だけを読み、各ワーカーへ短いタスク契約を渡します。

元19技能すべてに対応先があります。具体的な所在・列・結合キーの再レビューでは、既存119資料のうち113資料を更新し、詳細参照15資料を追加しました。現行は21技能・38参照を含む134知識ファイルです。[技術棚卸し](docs/technical-retention.md)に、読むべきパス・フィールドと資料別の修正をまとめています。[移行台帳](docs/migration.json)、[防御判断の対応表](docs/knowledge-decisions.json)、[表現検査](docs/expression-review.json)でも追跡できます。

追加の独立レビューでは、以前の対象外にあった技術候補808件の範囲を確認し、21参照をさらに補完しました。nativeのパス・列名・型・時刻・結合条件を保持し、未検証schemaは探索候補として区別しています。[ダブルチェック結果](docs/doublecheck-review.md)に実読範囲と残る条件を記録しています。その時点で検索非一致の非空543件は意味レビュー未実施でした。続く[反復レビュー](docs/review-cycles.md)では追加範囲を記録し、修正・独立再確認・commitを巡回ごとに実施しています。元資料の全記述について欠落ゼロとは判定していません。

今後も、元資料の本文・コード・画像・解答・ケースログを直接取り込みません。取り込み機はパスと内容のハッシュで追加・変更・削除を見つけ、独立して書いた汎用知識を検査・内容レビュー後に反映します。翻訳や名前の置換によるコピーも認めません。照合検査は法的な権利保証ではありません。

```bash
python3 -m metis.blue.runtime.knowledge_intake snapshot --source /path/to/source-checkout \
  --out .state/intake/baseline.json
python3 -m metis.blue.runtime.knowledge_intake diff --source /path/to/source-checkout \
  --baseline .state/intake/baseline.json --out .state/intake/delta.json
```

原稿の作成から反映・回復までの操作は[継続取り込み手順](docs/knowledge-intake.md)に分けています。

10巡の反復レビューで83群を改善しました。最後の巡にも3群の追加があり、指定された10巡上限で終了しています。未知の欠損ゼロとは判定せず、各巡の範囲・改善・未検証事項を[レビュー記録](docs/review-cycles.md)へ残しました。

### 7. 検証状況と導入時の確認

2026-09-30更新。接続・実製品の数値は過去に実施した試験の記録です。条件と限界は[検証結果](docs/verification.md)を参照してください。

| 検証 | 結果 |
| --- | --- |
| Python統合試験 | 現行180テスト成功 |
| 自作の使い捨て接続サーバー | SSH / RDP / VNC / SOCKS / OpenVPNの通信・拒否・後片付け9項目成功 |
| 実Splunk Enterprise 10.4.3 | ページ取得・行数上限・空結果の3ケース成功 |
| Elasticsearch | 模擬APIの契約試験成功。実製品は未検証 |
| 改訂前の評価v2・24ケース60項目 | UI表示Opus 4.6 / 4.8（Medium）、LAN内OllamaのQwen 27B Q4で各1回、全項目通過 |
| 初回改訂後の所在・フィールド評価 | Ollamaで2回とも23/24ケース・54/55項目。未合格として保存 |
| ダブルチェック後の拡張評価 | Ollamaで41/42ケース・102/103項目。追加18ケースは通過、Firefoxの起点年の誤答が残り未合格 |
| 10巡後の最終評価 | Ollamaで50/52ケース・131/133項目、未合格。Firefoxの起点年とSafariの参照先キーに誤答 |

「改訂前の評価v2」は、具体的なフィールド参照を補強する前の凍結本文に対する結果です。改訂後の[所在・フィールド評価](docs/benchmark.md#technical-locator-regression)と区別しています。改訂版のOpus 4.6 / 4.8は未再測定です。

初回v1のOpus 4.8には回答形式・ツール禁止の指示への違反があり、失敗記録も保持しています。v2は末尾の出力契約に加えて問題・参照も増やしたため、変更一つの効果やモデルの優劣を示す比較ではありません。Desktopのトークン数は未取得です。詳細は[評価仕様](docs/benchmark.md)と[プロトコル仕様](docs/readiness-protocols.md)へ記録しています。

```bash
.venv/bin/pytest tests/blue
python3 scripts/check_repo.py
```

実環境への導入時には、対象の証拠形式、収集範囲、SIEMのschemaと権限、必要な外部ツールを確認し、既知の正常・異常・欠損データで適合を検証してください。

## 詳細ドキュメント

- [ドキュメント一覧と読み順](docs/README.md)
- [CLI・設定・操作リファレンス](docs/cli-reference.md)
- [アーキテクチャと設計上の境界](docs/architecture.md)
- [技能の棚卸しと対応範囲](docs/skill-readiness.md)
- [具体的な証跡PATH・カラム・結合キーの棚卸し](docs/technical-retention.md)
- [独立ダブルチェックの範囲・補完・未確定事項](docs/doublecheck-review.md)
- [検証結果と未検証の範囲](docs/verification.md)
