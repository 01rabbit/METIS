# Issue #11 実ホスト検証記録（Claude Code → Codex CLI、2026-11-16）

Daybreak を Claude Code（Opus 5.5）、専門家を Codex CLI、統括を METIS、知識管理を MUNIN として、
ksnctf #8 と #33 を解いた記録。flag・候補・認証値は本文に書かない。

## 環境

| 項目 | 値 |
| --- | --- |
| METIS | `main` f620b33 から分岐した `work/issue11-codex-exec-specialist`（未コミットの変更を含む） |
| Daybreak | Claude Code、モデル claude-opus-5-5 |
| 専門家 | codex-cli 0.166.0、モデル `gpt-daybreak-blue-latest`（active catalog に登録した唯一の ID） |
| OS / Python | Darwin 27.2.0 / 3.12.13（`.venv`） |
| 状態 DB | 新規の `.metis-state/issue11-e2e-20261116.sqlite`。過去の run と MUNIN カードは引き継いでいない |
| 時刻 | 2026-11-16 09:35〜09:55 UTC 前後 |

## 1. Claude Code から Codex を起動・制御できるか

Claude Code の Bash から `codex exec` を直接起動でき、応答も返った。ただし、そのまま使うとユーザー設定の
`sandbox_mode = "danger-full-access"`、MCP、plugins などが効いてしまう。そこで、ツールを持たない専門家として
Codex を動かすドライバ `metis agent codex` を追加した（設計は `docs/ORCHESTRATION_RUNTIME.md` 6.1 節）。
既存の `BridgeHost` の考え方は変えていない。METIS は brief を返し、起動は Daybreak が行う。

`metis agent codex-probe --ping` の結果は `ready: true` だった。内訳は次の 3 点。

- ツールを使わない 1 ターン: 戻り値 0。出力スキーマどおりの JSON が返り、違反は検出されなかった。
- spawn カナリア: Codex に `collaboration.spawn_agent` を呼ばせた。spawn は失敗し（`no rollout found`）、
  stderr の router 行から `sub_agent_attempt` として検知した。
- シェル要求: `ls /` などを指示したが実行されなかった（`code-mode host is disabled`）。

確認の途中で次のことが分かった。`--disable multi_agent` を指定してもコラボレーション用ツールはモデルに
見えたままで、`--ephemeral` を外すと spawn が成功した。成功時も JSONL には item が出なかった。このため
ドライバは `--ephemeral` を必須とし、stderr による検知と probe のカナリアを併用している。spawn の防止は
現版 CLI の挙動に頼っており、仕組みとして不可能になったわけではない。

## 2. エージェント起動記録

両問題とも `metis plan` は `delegated` を選び、triage・crypto・web・critic の 4 担当を作った。
slot は全体 4、run ごとに 2。最初の dispatch では各 run 2 件が起動し、残り 2 件は `queued` になった。

| assignment | role | 結果 | intent | Codex ターン | 入力/出力 token |
| --- | --- | --- | --- | --- | --- |
| #8 `f0d8…:1` | triage | completed | 3 | 4 | 46,258 / 768 |
| #8 `f0d8…:2` | crypto | completed | 5 | 6 | 71,090 / 946 |
| #8 `f0d8…:3` | web | completed | 4 | 7 | 95,332 / 1,220 |
| #8 `f0d8…:4` | critic | completed（flag 形の報告が 1 回拒否された後） | 3 | 5 | 74,944 / 1,176 |
| #33 `362a…:1` | triage | completed | 3 | 4 | 47,034 / 811 |
| #33 `362a…:2` | crypto | completed | 5 | 6 | 68,639 / 1,251 |
| #33 `362a…:3` | web | failed（7 ターン目に codex が終了コード 1） | 4 | 7 | 87,813 / 916 |
| #33 `362a…:4` | critic | completed | 3 | 4 | 62,975 / 714 |
| #33 `c54a…:1`（第 2 wave） | triage | cancelled（実行中に cancel、in-flight の intent は `rejected_stale`） | 0 | 3 | 28,894 / 286 |
| #33 `c54a…:2`（第 2 wave） | crypto | completed（inconclusive） | 4 | 6 | 79,032 / 1,343 |
| #33 `c54a…:3/:4` | web / critic | queued のまま Daybreak が cancel | 0 | 0 | – |

`agent_job_log` の件数は、codex_turn 52、started 10、completed 8、failed 1、cancelled 1、rejected_stale 1。
Codex の thread ID はターンごとに `agent_job_log` に残っている。どのターンでもツール系 item は出なかった。
毎ターン出る `error` item は「code mode はフェイルクローズする」という通知だった。

## 3. 解析結果

ksnctf #8（Basic is secure?）: triage と crypto が、HTTP の 401 Basic 認証チャレンジまで特定した。
web と critic は `Authorization: Basic` のトークンを見つけ、METIS の `base64_decode` intent で復号した。
Daybreak は Codex の報告を使わず、pcap の `strings` 観測からトークンを取り直してパスワード部分を候補にした。
候補は画面に出さず、候補ファイルから `metis web submit` で送信した。公式判定は correct、`verified: true`。

ksnctf #33（HTTPS is secure.）: 第 1 wave で、TLS 1.0、RSA 鍵交換、cipher 0x0004（RC4-128-MD5）、
2 枚の似た証明書、そこから gcd 攻撃という仮説まで到達した。第 2 wave（`--reason` 付き）の crypto 担当は
2048 bit の modulus を hex 窓から取り出そうとしたが、観測の切り詰めと 6 intent の上限で完了しなかった。
以降は Daybreak が担当した。配布 pcap のスナップショットを実行せずにバイト列として解析し、2 本のフル
ハンドシェイク（CN=chihiro と CN=kei、シリアルが連番）から modulus を取り出した。gcd は METIS の
`gcd` action で計算し、1024 bit の公約数を得た。秘密鍵を再構成して ClientKeyExchange を復号し、
TLS 1.0 の PRF で鍵を導出した。session ID で再開セッションも対応づけて、4 本すべてを復号した。
`GET /flag.jpg` の応答 2 枚は 1 行の文字列を左右に分けた画像で、継ぎ目を拡大して 1 文字が分割されて
いることを確かめた。2 枚とも `metis codex add-file` で run に登録してある。公式判定は correct、`verified: true`。

MUNIN には、手法を抽象化したカードを 2 枚、`source_split: practice` で記録した（Basic 認証の取り出しと、
共有素数 RSA による TLS 復号）。flag 値は含めていない。

## 4. 機密の残存点検

候補 2 件と Basic トークンを照合値として、E2E 用 DB の全テーブルを走査した。`events`・`ctf_agent_reports`・
`munin_cards`・`ctf_hypotheses`・`agent_job_log`・`agent_actions` などで一致 0 件、flag 形の文字列も 0 件。
今回の変更ファイルにも一致は無かった。

一方で、Git 管理下の既存ファイル `writeups/ksnctf/8-basic-is-secure.md`、`writeups/ksnctf/33-https-is-secure.md`、
`writeups/ksnctf/files/8/8-solve.py` には一致する文字列が含まれている。これは今回の作業より前からある
ファイルで、照合ではファイル名と件数だけを見た。Daybreak も Codex もこれらを開いていない（Codex には
ファイルを読む手段が無い）。ただし、この 2 問はリポジトリの中では heldout になっていない。独立性の
主張は「参照しなかった」ことに留まる。writeup は削除せず、正解の値と解析知識の分離を #15 で扱う。

## 5. Issue #11 受け入れ条件との対応

| 条件 | 状況 | 根拠 |
| --- | --- | --- |
| 仕様 10 節を合成 fixture・ローカル HTTP・fake executor で検証 | ローカルで合格 | E2E 時点で pytest 319 passed / 10 skipped。重複 intent の修正後は 327 passed / 10 skipped（`tests/test_codex_specialist.py` 15 件、`tests/test_intent_identity.py` 8 件を含む） |
| 単純問題は不要 spawn なし、複合問題は異なる有限担当、モデルは active catalog のみ | 一部は実運用で確認 | 実運用では両問題とも異なる 4 担当（turn 4〜6、期限 600〜900 秒）で、使ったモデルは catalog の ID だけ。catalog 外のモデル指定は driver が拒否する（単体テスト）。単純問題の非 spawn は単体テストのみ |
| 並列数の制限、timeout・cancel・再起動後に二重操作や二重提出が無い | 一部は実運用で確認 | run ごと 2 slot で `queued` が残ることを実運用で確認。実 Codex の実行中に cancel すると、in-flight の intent は `rejected_stale`。修正後は 2 秒以内にプロセスを停止した（合成 run、`codex_killed`）。提出は各 run 1 回。controller 再起動を跨ぐ試験は既存の単体テストのみ |
| 専門家は公式送信・scope 拡張・資格情報管理をしない | 実運用で確認 | Codex にはツールが無く、8 種の Daybreak 専用 intent を CLI から送るとすべて拒否された（`intent_refused` 8 件）。spawn 試行はカナリアで検知した。提出・add-file・gcd の実行は Daybreak が行った |
| correct/incorrect/unknown/429/auth を区別し、incorrect 後は revision を要求 | 実運用では correct のみ | 他の判定は既存 `test_ctf_web.py` などの単体テストのみ |
| 候補・資格情報・private raw data を台帳・Git・MUNIN に残さない、heldout を再利用しない | 今回の変更と E2E DB については確認済み | 4 節のとおり。既存の writeups に解が含まれる点は別途判断が必要 |
| Python 3.12 で pytest・Ruff・mypy・manifest・build | ローカルで合格 | Ruff 合格、mypy 合格（42 files）、`metis validate` は valid、build 成功。このブランチの CI は未実行（push していない） |
| 既存 CLI/DB 互換と残る制限の文書化 | 対応済み | 新しいサブコマンドは `agent codex` と `agent codex-probe` だけで、DB スキーマは変更していない。`ctf_artifacts.ALLOWED_OPTIONS` は挙動を変えずにモジュール定数へ移した。制限は ORCHESTRATION_RUNTIME 6.1 節 |

skip の内訳: runtime の Docker 実行系 6 件、runner の Docker 統合 2 件（いずれも `METIS_TEST_DOCKER_IMAGE`
未設定）、sandbox イメージ 1 件、ブラウザ 1 件。いずれも未検証として扱う。

## 6. 残る制約と次の作業

- spawn の防止は Codex CLI の現挙動（`--ephemeral` で失敗する）に頼っている。CLI を更新したら
  `codex-probe --ping` で再確認する。隔離の強化は #16。
- intent の重複判定は options を少し変えるだけで回避でき、実際に Codex がそうした。検証の後に、正準化、
  再試験の上限、option 変種の上限で修正した（`core/intent_identity.py`、`tests/test_intent_identity.py`）。
  修正後のコードで実 Codex の E2E は再実行していない。
- X.509/TLS の構造を読む artifact tool が無く、#33 では専門家だけでは modulus に届かなかった。#17 で追加する。
- #33 web 担当の終了コード 1 は、当時 `turn.failed` の内容を記録していなかったため原因が分からない。
  現在のドライバは記録する。
- この記録はローカル実行に基づく。Issue のチェック更新や close は、レビューと CI を経てから行う。
