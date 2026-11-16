# Issue #16 Codex 専門家の OS 隔離（2026-11-16）

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

- spawn ツールそのものをモデルから隠すこと。#16 の受け入れ条件のうち、この 1 項目は未達。
  spawn された sub-agent は同じプロセス内にいるので、上記のファイル・ネットワーク制限の下にある
  （推測を含む: sub-agent が別プロセスとして起動する実装でも、子プロセスなので Seatbelt を継承する）。
- Linux / Windows の隔離。未実装で、起動を拒否する。
- Seatbelt やカーネル自体の脆弱性。`sandbox-exec` は Apple が非推奨としているが、現行の macOS で動作する。
- 許可した宛先（モデル API）へ送られる内容。プロンプトと観測は、設計上この宛先へ送られる。
- 読み取りを許可した範囲（Codex パッケージ、システムのディレクトリ）に含まれる情報。
