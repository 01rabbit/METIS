# Issue #16 Codex 専門家の OS 隔離（2026-11-16）

以下は初回導入時の記録であり、Linux の隔離実装より前の状態を含む。現在の実装・受け入れ状況は末尾の「2026-11-17 時点の更新」を参照。

## Codex CLI の版に依存する制限（整理）

codex-cli 0.166.0 で確認したこと。

- `--disable multi_agent` でも、`collaboration.spawn_agent` などのツールがモデルに見える。
- spawn は `--ephemeral` のときは失敗し、外すと成功する。成功時、JSONL に item が出ないことがある。
- `apply_patch`・`view_image`・MCP resource 系のツール名も見える。網羅的なツール一覧を取得する手段はない。
- `agents.max_threads` では spawn を止められない。

これらはモデルへの指示や CLI フラグで「形を整える」制御であり、版が変われば挙動も変わりうる。

## 追加した OS・プロセス・ネットワークの制御

`core/codex_isolation.py`。各ターンを次の条件で実行する。

| 層 | 制御 | 迂回できないことの根拠 |
| --- | --- | --- |
| ファイル | `sandbox-exec` のプロファイルで、ホーム・`/private/tmp`・`/private/var/tmp`・`/Volumes`・一時ディレクトリの読み書きを拒否する。例外は Codex パッケージの読み取りと、ターン専用ディレクトリだけ | カーネルが判定するため、Codex が持つツールの種類に依存しない。子プロセスにも継承される |
| Codex の状態 | ターンごとの `CODEX_HOME`（`auth.json` の写しのみ） | ユーザーの sessions・memories・config はホーム配下にあり、上の拒否に掛かる |
| ネットワーク | `(deny network*)`、例外はローカルプロキシへの接続のみ。プロキシは 443 番の許可リスト（`chatgpt.com`、`auth.openai.com`、`api.openai.com`）だけを中継する | 直接接続は Seatbelt が拒否する。プロキシを経由しても、許可リスト外の宛先は 403 で拒否され記録される |
| プロセス | ターンごとに新しいプロセスグループを作り、cancel 時はグループごと停止する | 既存の実装（PR #18） |
| 版 | 試験済みの版（0.166.0）以外は起動を拒否する | 版が変わると fail closed になる |
| 可用性 | 隔離が使えない環境（Linux など）では起動を拒否する。`--isolation none` は明示的な opt-out で、記録が残る | 既定は fail closed |

## 検証

- 単体テスト（`tests/test_codex_isolation.py`）:
  - プロファイルの生成と、不正なパスの拒否
  - プロキシによる他ホスト・他ポート・CONNECT 以外の拒否と記録、上流プロキシへの連鎖
  - `CODEX_HOME` の書き戻し規則（変化なし、書き戻し、原本変更時の拒否、不正な JSON）
  - npm シムからネイティブバイナリの解決
  - 試験済みでない版の拒否、隔離が無い環境での fail closed
- macOS の OS レベルのテスト（他の OS では skip）:
  - 生成したプロファイルの下でシステムのプログラムを動かし、保護領域の読み取り・一覧・書き込み、
    直接の通信、許可リスト外への通信がすべて拒否されることを確認した。
  - shell スクリプトの偽 Codex にも同じことを試させた。
- 実 Codex（probe）: 隔離のセルフテストは全項目合格。隔離下の ping は戻り値 0。テレメトリの
  `ab.chatgpt.com` は拒否され記録された。spawn カナリアは検知された。`auth.json` は変化なし。
- 実 Codex で CLI 側の防御をすべて外した試験: shell を有効にし、`--ephemeral` を外し、Codex 自身の sandbox を
  `danger-full-access` にし、すべての `--disable` を外した状態で、Codex に 10 回 shell コマンドを実行させた。
  - 保護ディレクトリのランダムな sentinel と `~/.codex/config.toml` の読み取りは
    `Operation not permitted` で、sentinel の値は出力に現れなかった。
  - 保護ディレクトリへの書き込みは拒否された。
  - `example.com` への通信は、プロキシ経由でも直接でも失敗した。
  - Codex 自身が許可リスト外の `*.oaiusercontent.com` へ 9 回接続を試み、すべて拒否されたが、動作は継続した。
  - 通常の運用では、この試験のような `command_execution` item はドライバが policy violation として扱う。

## 保証しないこと

- spawn ツール名をモデルから隠すこと。名前は見える。codex-cli 0.166.0 / 0.169.0 の試験済み構成では
  `--ephemeral` に頼らずCLIが呼び出しを拒否するが、将来版にはこの結果を外挿しない。
- （記録時点）Linux / Windows の隔離。未実装で、起動を拒否する。
- Seatbelt やカーネル自体の脆弱性。`sandbox-exec` は Apple が非推奨としているが、現行の macOS で動作する。
- 許可した宛先（モデル API）へ送られる内容。プロンプトと観測は、設計上この宛先へ送られる。
- 読み取りを許可した範囲（Codex パッケージ、システムのディレクトリ）に含まれる情報。

## 2026-11-17 時点の更新

- Linux 実行環境は Colima `rosetta` profile（Ubuntu 24.04、aarch64、4 CPU、約6 GiB、cgroup v2）。一時展開した Codex Linux arm64 CLI と METIS venv を使い、CI・challenge sandbox には認証を渡していない。
- `metis agent codex-probe --ping` を codex-cli 0.166.0 と 0.169.0 の両方で実行。両方 `ready: true`、ping return code 0、`CODEX_HOME` 認証は `unchanged`。各版で bwrap セルフテストは protected read/list/write 拒否、turn-dir write 許可、直接通信拒否、allowlist 外proxy拒否、NoNewPrivs、fork拒否、thread許可の全項目に合格。
- 両版とも `--ephemeral` を付けず、METIS の `agents.enabled=false`・MultiAgentV2無効化・thread上限の設定下で spawn カナリアを実行。実際の拒否 `code-mode host is disabled` を stderr router から検出し、`sub_agent_attempt` violation として分類した。ツール名自体はモデルに提示されるため、非提示とは主張しない。
- 負の対照として 0.169.0 で `--ephemeral` とagent無効化設定を外すと、`collaboration.spawn_agent` は成功し、子タスクが `HELLO` を返した。これにより拒否が `--ephemeral` やseccompの効果ではなく、テスト対象のCodex設定から来ることを確認した。子タスクはこの短い応答後に終了した。
- 受け入れに必要な2つのCLI版を実際に試した。今後は版ごとのfail-closed gateを維持し、未知版を明示的にprobeするまで許可しない。Windowsでは現状も隔離backendがなく、既定起動は拒否する。
