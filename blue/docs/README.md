# METIS Blue ドキュメント

[METIS Blueのプロフィールと利用仕様](../README.md)から始め、使う機能の詳細へ進んでください。この一覧は、現在の実装・操作・検証記録を目的別にまとめた入口です。

## はじめて使う

1. [README](../README.md)で利用モード、動作環境、依頼方法、保存先を確認する。
2. [CLIリファレンス](cli-reference.md)で `doctor` と `mock` の動作確認を行う。
3. 実調査に必要な[解析形式](artifact-tools.md)、[SIEM](siem-support.md)、[接続](connections.md)を選ぶ。
4. [技能の対応範囲](skill-readiness.md)と[検証結果](verification.md)から、導入先で追加確認する条件を決める。

## 機能別の仕様

| 知りたいこと | 読む文書 | 主な内容 |
| --- | --- | --- |
| オーナー・ワーカー・各機能の関係 | [アーキテクチャ](architecture.md) | 実行経路、モジュールの役割、状態とデータ、制御できる範囲 |
| コマンドを実行したい | [CLIリファレンス](cli-reference.md) | 引数、既定値、設定、実行・確認・再開、補助CLIへの入口 |
| 並列実行と状態を理解したい | [Runtime and state](runtime.md) | DAG、枠の一括予約、復旧、権限、トークン会計と旧DB移行 |
| 外部環境へ接続したい | [Connections](connections.md) | SSH/RDP/VNC/SOCKS/VPN/ブラウザー、認証、grant、接続の寿命、使い捨て試験 |
| SIEMを検索したい | [SIEM対応状況](siem-support.md) | Splunk/Elasticsearchの入力・制限・部分結果・終了確認・製品別対応 |
| 手元の証拠を読みたい | [Offline artifact readers](artifact-tools.md) | EML/MBOX、履歴SQLite、JSON、CloudTrail、EVTX XMLの形式・上限・出力 |
| 技能と外部ツールの境界を知りたい | [専門解析能力](analyst-capabilities.md) | 19分野の分析要件、同梱実装、外部エンジンが必要な形式 |
| 技能に不足がないか確認したい | [Skillsの棚卸し](skill-readiness.md) | 元19技能との対応、現行21技能・38参照、レビュー範囲と充足判定 |
| どこの値を見るか確認したい | [技術棚卸し](technical-retention.md) | 証跡PATH・table/column・型と時刻・join・結論の限界、既存119資料の再確認 |
| 継続する二重確認の結果 | [反復レビュー](review-cycles.md) | 各巡の指摘・修正・独立再確認・commitと停止条件 |
| 再確認で何が見つかったか | [ダブルチェック](doublecheck-review.md) | 追加候補808件の実読範囲、21参照の補完、未確定schemaと未読範囲 |
| ナレッジを更新したい | [継続取り込み](knowledge-intake.md) | コピー禁止、差分検知、独立原稿、検査・内容レビュー・適用・中断回復 |
| 移行先や履歴を検査したい | [知識監査](knowledge-audit.md) | 棚卸しの母集団、ハッシュ照合、参照とGitオブジェクトの監査 |
| モデルを評価したい | [Benchmark methodology](benchmark.md) | CLI/Desktop/Ollama、合成課題、採点、使用量、実測結果と比較の限界 |
| 評価v1/v2の違いを知りたい | [Readiness protocols](readiness-protocols.md) | 凍結した入力、末尾契約、旧版互換性、厳密JSON採点、試行したツールの扱い |
| 何を検証できているか知りたい | [検証結果](verification.md) | テスト・実通信・実製品・モデル評価を分けた結果と未検証条件 |

詳細仕様の一部は英語です。製品固有の認証方式、入力形式、上限、終了不明時の対応は、リンク先の仕様を優先して確認してください。

## 実行時の指示と知識

| 入口 | 役割 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | オーナー・ワーカーの運用契約。自己完結した問い、権限、証拠、私有記録、取り込みの扱い |
| [CLAUDE.md](../CLAUDE.md) | Claudeから共通契約を読む入口 |
| [blue-owner](../skills/blue-owner/SKILL.md) | 依頼の受領、専門技能の選択、配分、照合、利用者への報告 |
| [worker contract](../skills/blue-owner/references/worker-contract.md) | ワーカーへ渡す証拠・質問・期限・権限・出力の契約 |
| [技能ライブラリ](../skills/) | 各専門領域の `SKILL.md` と必要に応じて読む参照 |
| [検知ライブラリ](../detections/) | 検知候補、調査カード、ルールの参照。配備済みルールの一覧ではない |
| [対応手順](../playbooks/) | 証拠に基づく調査・対応の進め方 |

運用説明、分析知識、実装済みアダプター、実証済みの条件は別の情報です。技能に手法の記載があるだけで、その解析エンジンや接続APIが同梱されているとは扱いません。

## 構造化した台帳

以下は仕様本文を補うJSONの記録です。私有ケースの本文や回答を含めず、対応関係とハッシュ等を保持します。

| 台帳 | 内容 |
| --- | --- |
| [migration.json](migration.json) | 元技能・参照等の対応先と現行の対象ハッシュ |
| [knowledge-coverage.json](knowledge-coverage.json) | 元の追跡ファイル全件のハッシュと処遇 |
| [knowledge-decisions.json](knowledge-decisions.json) | 防御判断ごとの採否・修正・対応先 |
| [expression-review.json](expression-review.json) | 現行知識の表現照合と検査対象ハッシュ |
| [technical-retention.json](technical-retention.json) | 134資料の具体的な欠落・復元・保持、元資料の読解範囲、独立レビューと現行hash |
| [doublecheck-review.json](doublecheck-review.json) | 追加候補の実読座標、初回との集合照合、分類・残る条件 |
| [intake-ledger.json](intake-ledger.json) | 継続取り込みで反映した知識の公開可能な記録 |

これらの台帳や一致検査は、元資料の全記述との意味的等価性や法的な権利保証を示すものではありません。

## 記録を混ぜない

- 実行の会話・使用量・状態は、標準では `.state/state.sqlite3` と `.state/reports/` に保存する。
- 調査の証拠・時系列・所見は、ケース記録の `logs/<CASE_ID>/` に保存する。
- 評価の生回答、接続情報、取り込み原稿、レビュー記録は私有領域に置く。
- `.state/` と `logs/` はGitへ追加しない。文書にはレビュー済みの一般仕様と検証結果の要約だけを載せる。

ファイル配置の説明は標準設定です。`--db` や `SOCLOG_ROOT` を変える場合は、実際の保存先とGit除外を利用者が確認します。生の証拠や秘密情報を、説明例・技能・公開台帳へ転記しないでください。

## 文書を更新するとき

実装を変えたら、関係する詳細仕様を先に更新し、READMEの対応範囲・既定値とこの一覧を揃えます。実測結果を更新するときは、モデル・製品版・入力・実行条件・失敗・未検証条件を残します。説明だけの更新を、新たな実モデルや実製品の検証結果として扱いません。
