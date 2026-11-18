# 専門家AIオーケストレーションの実行層（Issue #11）

[CTF_ENVIRONMENT_AND_ORCHESTRATION.md](CTF_ENVIRONMENT_AND_ORCHESTRATION.md)（以下「仕様」）の
P1〜P5 を実装した結果と、使い方・互換性・残る制約をまとめる。

## 1. 構成

| 層 | モジュール | 役割 |
| --- | --- | --- |
| P1 契約・policy | `core/agent_contracts.py` | `SpecialistProfile` `Assignment` `ModelSelection` `ExecutionRecord` `CompactReport` `WaveDecision`（すべて `extra=forbid`、有限値、schema_version 2）。`decide_wave` と `select_model` は純粋関数 |
| 計画・台帳 | `core/ctf_orchestration.py` | `plan_agent_wave(context, force_mode=)` は決定的。`AgentLedger` は wave と compact report の台帳 |
| P2 ホスト | `core/agent_host.py` | `capabilities / spawn / poll / send / cancel / collect`。`BridgeHost`（既定）、`SequentialHost`、テスト用 `FakeHost` |
| P3 scheduler | `core/agent_scheduler.py` | slot予約、run固定のCodex model-turn予約、attempt、deadline・intent上限、cancel/retry/release、tool intent の仲介 |
| 単一writer | `core/run_lock.py` | run ごとの短い状態ロックと、キャンセルを妨げないtool-operation lock。intent予約・状態遷移・event追記・公式提出を直列化する |
| P5 大会 | `core/ctf_contest.py` | run と問題の同一性検査、dispatch の timebox 強制 |

## 2. 1問題の流れ（Daybreak）

```sh
.venv/bin/metis plan RUN_ID                       # auto: 単純なら sequential、独立調査があれば delegated
.venv/bin/metis agent dispatch RUN_ID WAVE_ID     # 必須担当を queued にし、slot の範囲で開始。brief を返す
#  → Daybreak は brief をホストのサブエージェント（Codex/Claude）に渡す
.venv/bin/metis agent intent RUN_ID ASSIGNMENT_ID --attempt ATT --file intent.json   # 担当のツール要求
.venv/bin/metis agent complete RUN_ID ASSIGNMENT_ID --attempt ATT --file report.json # compact report
.venv/bin/metis agent tick                        # deadline 超過・回収・lease 期限の処理
.venv/bin/metis agent synthesize RUN_ID WAVE_ID   # 旧 field + decision（v2）
.venv/bin/metis plan RUN_ID --reason "異なる未解決仮説"   # 次 wave（条件を満たす場合のみ）
```

- **sequential**: 必須担当は空。`daybreak_covers` の役割を Daybreak が兼任する。台帳に missing は残らない。
- **delegated**: 2カテゴリ以上、または宣言/推定カテゴリ＋配布物2件以上のとき。2〜4件の異なる role。
  カテゴリの出所（declared / triage / default）と理由を `decision` に記録する。triage 推定は「未検証」と明記。
- `--mode sequential|delegated` で上書きできる（旧動作の再現は `--mode delegated`）。
- `assignment.inputs.artifacts` を明示すると、その割当の brief には許可された artifact 名だけを渡す。
  `artifact / derive / view` intent と report の `artifact_refs` も同じ集合に制限し、範囲外は fail closed。
  フィールド省略時は既存互換で run の artifact scope を使い、明示した空リストは artifact 権限なし。
  成功した `derive` が生成した artifact だけは、その作成元 assignment の集合に追加する。
- dispatch時の各assignment deadlineは、そのrunの現在の `seconds_remaining` で上限をかける。
  同一runの並列workerが個別deadlineによってrun全体のwall-clock期限を越えないようにする。
  Tool intentのaction数もrun単位で共有する。CodexCLI driverでは、実際のprovider呼出直前に
  run固定のmodel-turn予算（既定24、`metis agent slots --specialist-turn-budget N`）をSQLiteで予約する。
  失敗・timeout・retryも予約消費に数え、run間の設定変更や再起動で上限は増えない。
  `codex cancel RUN_ID` 後は enqueue・retry・dispatch・model-turn予約を拒否する。
  dispatchのslot予約とhost起動の間にもrun状態を再確認し、host起動はrun lock内で行う。
  schedulerのtickとspecialist driverはrunのcancel状態をjob状態とは独立に確認し、
  queued jobを取消し、実行中jobを停止する。停止未確認は`unknown`としてslotを保持する。
  実行中のCodexも同じrun状態を停止signalとして使い、取消後の出力・reportをcommitしない。
  取消前に予約したmodel turnは、provider未呼出や実行中取消の場合も消費したままにする。
  bounded autopilot はこの予約機構を明示するrunnerを必須にし、そうでなければdispatch前に停止する。
  BridgeHost経由でDaybreakが手動で直接起動するsubagentには強制できず、その経路はbounded autopilotの
  保証外として扱う。token/costは利用量報告が
  不確実なため上限予約できず、未知なら`unknown`のまま。実モデルの単独対delegated比較も未実施で、
  Issue #6の受入れゲートは未達。

### tool intent（担当 → controller）

```json
{"kind": "artifact", "tool": "text", "artifact": "00-cipher.txt", "options": {}}
{"kind": "data", "tool": "base64_decode", "data": "aGVsbG8="}
```

- `kind` は `data` / `artifact` / `derive` のみ。`submit` `attest` `grant` `auth` `remote` `web` `sandbox`
  `delegate` `extend` は「Daybreak 専用」として拒否し、ログに残す。
- 同じ run で同じ action identity の再実行は拒否する。identity は `core/intent_identity.py` で正準化する。
  具体的には、整数 option の型を揃え（`"0x10"` と `16` を同一視）、既定値を補い、byte 窓を artifact サイズで、
  PCAP のパケット数を実レコード数で打ち切り、構造化 data の JSON をキー順で正準化し、hex 入力の空白と
  大小文字を無視する。identity は重複判定にだけ使い、ツールは要求どおりに実行する。
- 重複判定の範囲は attempt 単位（#23 で変更）。状態を持たない専門家は他の担当の観測を見られないため、他の attempt が
  実行済みの要求は新しい attempt が実行できる。ただし同じ正準要求は run 全体で 8 回（`RUN_REPLAY_LIMIT`）まで。
- 再試験は attempt ごとに 1 回（`MAX_RETESTS`）まで。`new_evidence` には、前回の実行より新しく、かつ別の
  action が生んだ観測イベントを挙げる必要がある（古いイベントや同じ action 自身のイベントは数えない）。
- 1 attempt の中で、同じ artifact に同じツールを option を変えて使えるのは 3 通り（`FAMILY_LIMIT`）まで。
- 拒否は `agent_job_log` に `intent_duplicate` / `intent_variant_limit` として残り、メッセージは引用すべき
  既存のイベント番号を示す。
- intent identity と specialist turn は実行前に run lock の下で予約し、同じidentityのin-flight再実行も拒否する。
- bounded artifact処理は別のrun単位operation lockで直列化する。長いsandbox処理中は状態lockを解放するため、cancel/tickは処理結果を待たずにworkerを停止できる。
- 操作終了時にattempt state/deadlineを再確認し、cancel・timeout・recovery後のlate resultと派生artifact scopeはcommitしない。予約済みturnは実行失敗時も返却しない。
- 各成功したtool intentはassignment単位の `max_turns` とrun全体の既存action予算を消費する。
  CodexCLI経路では別に、providerを呼ぶ前にrun-wide model-turn reservationを1つ消費する。
  model turnは失敗・timeout・再試行でも返金しない。いずれかの上限超過は追加tool/model実行を拒否する。

#### モデル呼び出し枠の借用（任意の実験経路）

`AgentScheduler.enqueue(run_id, wave_id, dynamic_borrowing=True)` は、run の
**最初の wave のみ**で利用できる。assignment が 2 件以上あり、その件数が run の
確定済み呼び出し上限以下の場合に限る。既定では従来の固定枠を使う。
有効にした assignment は、run の上限とスキーマ上の 20 intent の小さい方まで
自分の枠を使える。run 全体のモデル呼び出し上限と action 上限は変わらない。

同じ run lock と SQLite transaction の中で、まだ一度も予約していない
queued または running の各 peer に最初の 1 回を残す。残りがこの保護枠に
達した assignment は `model_turn_peer_reserve` で失敗する。この仕組みは
最初の呼び出し機会を残すもので、呼び出しの成功や job 完了は保証しない。
running の peer がまだ呼び出しを始めていない場合にも直ちに失敗するため、
高速な job が先に止まる可能性がある。今後の事前登録した測定で、この
公平性と完了率を確認する。再試行分は同じ run 上限から消費し、返金しない。
取消後は新たに予約できない。この変更では通常の実行や benchmark に
自動で有効化しない。

### 状態と attempt

`queued → running → completed | failed | cancelled | timed_out`、停止を確認できない場合は `unknown`
（slot を占有したまま。`metis agent release ASSIGNMENT_ID` で確認後に解放）。
再実行（`agent retry`）は新しい attempt を作り、最大3回。古い attempt の intent・報告は拒否して監査ログ
（`agent_job_log`）に残る。

### slot

同時実行数 = `min(ホストの上限, 全体slot, run ごとのslot, wave の担当数)`。
`metis agent slots --global 4 --per-run 2` で設定（既定 4 / 2）。足りない分は `queued` のまま。
大会の `max_parallel`（同時に着手する問題数）とは別の上限で、両方が効く。
model-turn budgetは同コマンドの `--specialist-turn-budget` でrun開始前に指定できる（既定24、範囲1–256）。
runの最初のwaveをqueueした時点で上限をsnapshotし、後からの設定変更は既存runへ適用しない。


### 共有リソースとスコープ付き許可

- 名前付きリソース（`sandbox`、`browser` など）の容量を `metis resource configure NAME --capacity N`
  で設定すると、同じ状態ファイルを使う全プロセス（並列の専門家、スウォーム、別の run）で共有される。
  要求する枠の組は1トランザクションで全部取るか何も取らない。容量を設定していないリソースは制限しない。
  - `metis sandbox run` は `sandbox` を1枠、`web open --render` は `browser` を1枠借りる（待機の上限はそれぞれ300秒と120秒）。
  - lease には期限がある。期限切れの回収（`metis resource reap`）と明示の解放（`metis resource release`）は、
    保持者の停止を確かめてから行う。容量は、借りている枠数より小さくできない。
- `metis permit issue RUN TASK RESOURCE ACTION --reason ... [--ttl 300] [--uses 1]` は、外部の状態を変える
  操作（attack-defense のパッチ投入など）に対する、完全一致・期限付き・回数付きの許可を出す。
  ワイルドカードは拒否する。消費（`ScopedPermits.consume`）は原子的で、最後の1回を二重に使えない。
  発行は Daybreak（オーナー）だけが行う。

### モデル

`metis agent slots --catalog-file models.json --current-model ID` で、ホストがその場で示したモデル一覧
（`[{"id": ..., "tier": "lower|standard|strong"}]`）を登録する。選択は一覧の中からだけ行い、該当 tier が
無ければ現在のモデルを再利用（`fallback_reason` を記録）。昇格には理由が必須。トークン・費用はホストが
報告しない限り `unknown`。

## 3. 統合と提出

- `synthesize` の旧 field（`complete` `missing_assignments` `submission` `start_another_wave`）は意味を
  変えていない。新しい判断は `decision`（schema_version 2）にある。
  - `ready_for_synthesis`: 必須担当がすべて「報告済み」か「失敗/取消/時間切れで終了」
  - `ended_without_report`: 終了理由つきの担当（成功扱いしない）
  - `new_wave.allowed`: 未解決担当なし・予算あり・未解決（inconclusive）または反証された仮説あり
  - `submission.synthesis_is_not_permission: true`
- 次 wave は前 wave が `ready_for_synthesis`、予算あり、`--reason` に異なる仮説、のときだけ作れる。
- 報告は `CompactReport` で検証（未知 field 拒否、長さ、存在するイベント番号、登録済み artifact 参照、
  flag 形の文字列拒否、重複 action は新しい証拠がある場合のみ許可）。候補は報告に入らない。
- 公式提出は従来どおり Daybreak が `metis web submit --candidate-file`（またはブラウザ＋`attest`）で行う。
  run lock により同じ run への並行提出は直列化され、送信途中で中断した `pending` は 120 秒後に `unknown`
  （送信済みの可能性あり）として残る。`pending` がある間は別候補を送らない。incorrect 後は
  `memory reason`（revised/rejected）なしに新候補を送れない（既存の gate）。

## 4. 大会連携

- `contest update` で run を紐付けるとき、web run の `challenge_id` または問題 URL がボードの問題と
  一致しなければ拒否する（ローカル intake の run は比較対象がないため検査しない）。
- `contest dispatch` は `timebox_until`（最大30分）を記録し、次回の dispatch（または
  `ContestBoard.enforce_timebox`）で期限切れの問題を `blocked`＋メモにする。再 queue / abandon は明示的に行う。
- スウォーム（`metis swarm`）の lease とは別の仕組みで、互いに干渉しない。
- 前提問題（`prerequisites`）が循環する追加は拒否する。前提が `abandoned` になった（上流を含む）queued の問題は
  `board` と `dispatch` の `blocked_by_prerequisites` に原因と共に出す。黙って待たせ続けない。

## 5. 受け入れ条件との対応（仕様10章）

| テスト | 実装・検証（tests/） |
| --- | --- |
| 単純問題 | `test_agent_orchestration.py::test_simple_problem_is_sequential_without_missing_assignments` |
| 複合問題 | `test_compound_problem_gets_distinct_finite_assignments`、`test_deadlines_turns_and_stale_attempts` |
| モデル選択 | `test_model_selection_uses_only_the_active_catalog` |
| 全体slot | `test_global_and_per_run_slots_are_never_exceeded`、`test_concurrent_dispatch_does_not_double_reserve` |
| 権限 | `test_specialists_cannot_submit_grant_auth_or_delegate` |
| 注入・機密 | `test_triage_categories_are_recorded_and_injection_does_not_change_policy`、報告の flag 拒否（`test_ctf_orchestration.py`） |
| 報告 | `test_reports_reject_bad_evidence_fields_and_waves`、stale attempt |
| 統合・次wave | `test_new_wave_requires_resolution_budget_and_a_different_hypothesis`、`test_fake_executor_completes_and_failures_release_slots` |
| 公式検証 | 既存 `test_ctf_web.py`（CTFd/ksnctf/HTML の correct/incorrect/unknown/429/auth/redirect） |
| 修正 | 既存 `test_ctfd_intake_wrong_answer_replan_correct_answer_and_reopen` |
| 再起動・並行 | `test_deadlines_turns_and_stale_attempts`（別 scheduler で tick）、`test_concurrent_intents_respect_the_run_budget`、`test_parallel_submissions_are_serialized_and_pending_sends_are_kept`、`test_cancel_without_confirmation_keeps_the_slot_until_released` |
| run wall-clock共有 | `test_assignment_deadline_is_capped_by_shared_run_wall_budget` |
| 大会 | `test_contest_binding_and_timebox`、既存 `test_ctf_contest.py` |
| 知識 | 既存 `test_ctf_knowledge.py`（verified 前の成功 card 拒否、失敗根拠、heldout 除外） |

## 6. 互換性

- 既存 CLI（`plan` `agent report` `agent synthesize` `codex plan`）はそのまま動く。`plan` に `--mode` と
  `--reason` を追加した。
- 既存 DB: `ctf_agent_reports` に `attempt_id` `action_identity` 列、`ctf_contest_challenges` に
  `timebox_until` 列を追加（`ALTER TABLE`、既存行は NULL）。新テーブル `agent_jobs` `agent_job_log`
  `agent_actions` `agent_config`。
- 旧 wave（schema_version なし）は全担当を必須として扱い、migration で complete に変えない。
- **挙動の変更**: 単純な問題では `metis plan` が担当を作らない（sequential）。以前の全担当計画が必要なら
  `--mode delegated`。2つ目以降の wave は `--reason` と前 wave の解決が必要。

## 6.1 Codex CLI 専門家ドライバ（Claude Code → Codex）

`metis agent codex RUN_ID ASSIGNMENT_ID --attempt ATT`（`core/codex_specialist.py`）は、dispatch 済みの
1 attempt を Codex CLI で実行する Daybreak 側のドライバ。`BridgeHost` の設計（METIS は brief を返し、
起動は Daybreak が行う）はそのままで、Daybreak がホストのツール（Claude Code の Bash）からこの
コマンドを起動する。

- 各ターンは `codex exec --ignore-user-config --ignore-rules --sandbox read-only` で、空の作業
  ディレクトリ、縮小した環境変数（トークン類を渡さない）、`approval_policy="never"`、`web_search="disabled"`、
  shell・multi_agent・apps・plugins・hooks・browser/computer use・code mode などの feature 無効で動く。
  `shell_tool` を無効化できない CLI では起動を拒否する（fail closed）。
- Codex は出力スキーマに沿った JSON（intent / report / fail）を返すだけ。intent は
  `AgentScheduler.intent` を通り、Daybreak 専用の種別は拒否・記録される。報告は `complete` の検証を通る。
  各ターンは状態を持たず、brief とその attempt 自身の手順だけを渡す（Daybreak の会話履歴は渡さない）。
- 検知（多層防御）: イベントにツール系 item（command_execution・file_change・mcp_tool_call・web_search・
  collab_tool_call）が出る、または stderr の tool router にサブエージェント起動の痕跡がある場合、attempt を
  `failed`（`policy_violation`）にする。
- cancel: ドライバは 2 秒ごとに job 状態を確認し、取り消されたら Codex のプロセスグループを停止して
  `codex_killed` を記録する。
- OS 隔離（#16、`core/codex_isolation.py`）。各ターンを macOS の `sandbox-exec` または Linux の bubblewrap 下で実行する。
  - ホーム・`/private/tmp`・`/private/var/tmp`・`/Volumes`・一時ディレクトリの読み書きを拒否する。例外は
    Codex パッケージの読み取りと、そのターン専用ディレクトリの読み書きだけ。
  - `CODEX_HOME` はターンごとに作る。中身は `auth.json` の写しだけで、ユーザーの sessions・memories・
    config・skills は見えない。ターン中に更新されたトークンは、原本がその間に変わっていない場合に限り
    書き戻す。
  - 外向き通信は、ローカルの CONNECT プロキシ（443 番、`chatgpt.com`・`auth.openai.com`・`api.openai.com`
    のみ）以外を拒否する。拒否した宛先はターンごとに記録する。
  - Linux は bubblewrap の名前空間と capability 制限に加え、Codex の実行系に seccomp を適用する。`fork`、`vfork`、プロセスを作る `clone` と `clone3` を拒否する。スレッド生成は許可し、`exec` 自体は制限しない。macOS Seatbelt と同じ保証ではない。
  - 隔離が使えない環境では起動を拒否する。`--isolation none` は明示的な opt-out で、記録が残る。
  - 試験済みでない Codex CLI の版も拒否する（`--allow-untested-codex` で解除）。版は各 turn の直前に再確認する。
- 専門家は `view` intent で登録済みの画像を次のターンに添付させられる。答えは `candidate` で非公開に渡す（0600 のファイル、
  DB には digest のみ）。Daybreak は `metis agent candidates RUN` でファイルのパスを受け取り、`metis web submit --candidate-file` で提出する。
- `metis agent codex-probe --ping` は、隔離のセルフテスト、実ターン 1 回、spawn カナリア 1 回を実行し、
  `ready` を返す。
- usage（トークン数）は Codex の報告値を `agent_jobs.usage` に記録する。費用は `unknown`。
  1 ターンでも報告の無い項目は 0 で補わず `null` とし、`unknown_fields` に名前を残す。報告された分だけの和は `known_subtotals` に置く。
- モデルは `metis agent slots` に登録した active catalog の ID だけを使う。

確認済みの制約（Codex CLI 0.166.0 と 0.169.0、2026-11-16〜17）。サブエージェント起動の制限は、この版の挙動に依存する:

- `--disable multi_agent` でも `collaboration.spawn_agent` などのツールがモデルに見え続ける。`--ephemeral`
  0.166.0 と 0.169.0 のLinux実測では、`--ephemeral` を外した状態でも `agents.enabled=false` と
  MultiAgentV2無効化設定によりspawn要求が `code-mode host is disabled` で拒否された。拒否文はstderr
  のrouter記録からsub-agent試行として検知し、attemptをpolicy violationで終了する。ツール名自体は
  モデルに提示される。seccompはOSプロセス生成を別途拒否するが、in-process spawn拒否はCodex CLIの
  バージョン依存であり、未試験版はfail closed。
- `apply_patch`・`view_image`・MCP resource 系のツール名もモデルには見える。網羅的なツール一覧を
  取得する手段はないが、ファイルの読み書きは OS 側で制限している。
- OS 隔離は macOS が Seatbelt（fork を禁止し、exec は Codex 本体だけ）、Linux が bubblewrap（名前空間・capability 0・
  NoNewPrivs、プロセス生成を禁止、通信は Unix ソケット経由のプロキシのみ）。Windows は未実装で、起動を拒否する。Linux 上の実 Codex は未検証
  （`docs/reports/issue16-isolation-backends-2026-11-16.md`）。Seatbelt や
  カーネル自体の脆弱性による脱出、許可した宛先（モデル API）へ送られる内容は、対象外。
- E2E 時点の重複判定は、生の action identity の一致だけを見ていた。そのため `length` を 1 変える、無関係な
  イベントを `new_evidence` に挙げる、といった操作で回避でき、Codex は実際にそうした。正準化、再試験の上限、
  option の変種の上限で塞いだ（`tests/test_intent_identity.py`）。ただし意味の同値性を網羅しているわけでは
  ない。例えば `strings` の `limit` を変えれば、結果が同じでも別の要求として扱われる。
- METIS の artifact tool には X.509/TLS の構造解析が無く、観測は 12000 文字で切り詰める。2048 bit の
  modulus を hex 窓から抽出する作業は、6 intent の上限内で完了しなかった（ksnctf #33 の実例）。#17 で
  artifact tool `x509`（DER/PEM の証明書）と `tls_certificates`（PCAP/PCAPNG の TLS Certificate handshake）
  を追加し、RSA の `n`・`e` を intent で取得できるようにした。TLS 1.3 の証明書は暗号化されているため
  取得できない（理由コード `tls13_certificates_encrypted`）。

## 6.2 実ホスト受け入れの再実行手順

PR #14 の受け入れ手順を、現行のコマンドに合わせて短くしたもの。結果は `docs/reports/` に日付付きで残す。
値（flag、候補、鍵）は記録に書かない。

1. `metis agent codex-probe --ping` で `ready: true` を確認する。隔離のセルフテスト、ツールを使わない ping、spawn カナリアが含まれる。
   Codex CLI の版と隔離方式を記録する。
2. 新しい状態 DB に合成の問題か練習問題を取り込む。`metis web open` の `evaluation.split` で practice か heldout かを記録する。
3. `metis agent slots --catalog-file` で、ホストが示したモデルだけを登録する。`metis plan` で `delegated`、異なる 2〜4 担当、有限の turn と期限を確認する。
4. `metis agent dispatch` の後、各担当を `metis agent codex RUN ASSIGNMENT --attempt ATT` で並列に起動する。
   thread ID・トークン数・隔離の要約は `agent_job_log` に残る。
5. 境界の確認: Daybreak 専用の intent（submit・grant・auth・remote・web・sandbox・delegate・extend）を CLI から送り、
   すべて `intent_refused` になることを確かめる。重複・オプション変更・古い証拠の引用が `intent_duplicate` になることも確かめる。
6. 実行中に `metis agent cancel` を送り、`codex_killed` が記録され、Codex のプロセスが残らないことを確かめる。
   その後に送られた intent が `rejected_stale` になることも確かめる。
7. `metis agent synthesize` で、未解決の担当が無いこと、`synthesis_is_not_permission: true` であることを確認する。
   候補は `metis agent candidates` で受け取り、Daybreak だけが `metis web submit --candidate-file` で提出する。
8. 公式判定の各種（correct・incorrect・unknown・429・auth）は、ローカル HTTP の単体テスト（`test_ctf_web.py`）で確認する。
9. 機密の残存点検: 状態 DB の全テーブル、MUNIN、Git の差分、保管庫の外に、候補・トークン・鍵が無いことを照合する
   （値は表示せず、件数だけを記録する）。

実施例: `docs/reports/issue11-codex-e2e-2026-11-16.md`、`issue11-codex-retry-e2e-2026-11-16.md`、
`issue23-tls-decrypt-2026-11-16.md`、`issue16-isolation-backends-2026-11-16.md`。

## 7. 残る制約

- `BridgeHost` / `SequentialHost` は METIS 側の契約（slot・attempt・intent・報告）を強制するが、ホストの
  サブエージェント内部の shell 操作までは制御できない（仕様4章の「推論ホストの全 shell 操作の強制制御」は
  非目標）。制御できるのは METIS の CLI を通る操作だけ。
- METIS からホストのサブエージェント API を直接起動はしない（Codex/Claude のサブエージェントは呼び出し元
  セッションの機能）。`spawn` は brief を Daybreak に返し、Daybreak がホストのツールで起動する。
- `abstract_text` は簡易の flag/秘密 guard であり、完全な DLP や OS 権限分離ではない。
- 大会の `max_parallel` は、スウォーム用に 1〜16 を許容している（仕様の 1〜8 より広い）。
- 仕様の時点（3324e35）以降に追加された動的実行 `metis sandbox`（ネットワークなし・読み取り専用の
  コンテナ）は、この層の intent からは呼べない（Daybreak 専用）。担当が動的確認を要する場合は報告の
  `next_action` に書き、Daybreak が実行する。
- 合成 fixture での結果は実大会の solve 率を意味しない。

### Linux process creation restriction

Linux の bubblewrap 内では、転送器を起動した後に seccomp を Codex の実行系へ適用する。
`fork`、`vfork` と、`CLONE_THREAD` を持たない `clone` を拒否し、検査できない `clone3` は
`ENOSYS` で拒否して libc の `clone` フォールバックを可能にする。対応 CPU は x86-64 と aarch64。
フィルタ設定に失敗した場合は Codex を起動しない。スレッドは許可する。`exec` 自体は制限しないため、
既存プロセスの置き換えは可能であり、macOS の実行ファイル制限と同じ保証ではない。
Codex の in-process `collaboration.spawn_agent` は OS のプロセス生成ではなく、このフィルタでは止められない。
Linux 実 Codex 0.166.0 / 0.169.0 の互換性試験と、METISのagent無効化設定によるspawn拒否を実機確認した。
seccomp単独では拒否しない。拒否経路、陰性対照、auth扱いは
`docs/reports/issue16-linux-real-codex-2026-11-17.md` を参照。

## 6.3 Bounded autopilot

`metis agent autopilot RUN_ID --max-waves N` runs the latest wave (or creates the initial
plan) through the existing scheduler and isolated Codex specialist driver. N is 1–10 and
counts waves inspected in this invocation, including a resumed wave. Sequential work,
pending candidates, unresolved existing attempts, other active waves, unavailable slots,
and non-spawn failures stop for Daybreak. Spawn failures alone are retried within the
scheduler's attempt limit. An autopilot lock prevents simultaneous drivers for one run;
existing running or unknown attempts are never relaunched after a restart. Reconcile
those explicitly with the scheduler before retrying. Candidate values stay in the private
candidate store; this command never submits or expands scope.

A subsequent wave requires both the synthesis gate and Daybreak's explicit selection of
a materially different unresolved hypothesis. Supply `--continuations FILE` as a JSON
array of objects with `wave_id`, `report_id`, and `reason`. The reason must exactly match
an inconclusive report's `next_action` and must not repeat a previous wave reason. This
checks provenance and literal repetition, not semantic difference: Daybreak remains
responsible for that judgment. Missing or invalid selections stop the driver. A selection
for a later wave can be supplied when resuming after its report exists.

Each invocation persists an answer-free row in `agent_autopilot_runs`: elapsed time,
wave count, stop reason, Daybreak handoff, scheduler operations, specialist turns, and
token usage when the provider reports it. Unknown token counts and dollar cost remain
explicitly unknown. These counters measure controller activity; they do not establish
improved solve rate or reduced human work.
The synthetic one-wave comparison and persisted-metric check are recorded in
`docs/reports/phase4-autopilot-equivalence-2026-11-17.md`; zero specialist jobs leave
token counts `unknown` rather than reporting a measured zero.

### P3: MUNIN retrieval and split controls

`codex_sessions.evaluation_split` classifies local runs as `practice`, `competition`,
`heldout`, or `unlisted`. Existing databases migrate to `unlisted`, which is deliberately
ineligible for retrieval. The practice generator labels its exercises; web intake uses
the existing evaluation classifier; CLI `codex start` and `codex intake` accept an
explicit split. MUNIN lookup for specialist briefs and web intake is available only for
practice and competition runs. Held-out and unlisted runs receive no prior cards.
Specialist briefs present retrieved cards as untrusted experience with applicability
conditions, never as evidence or answers. `metis agent slots --no-memory-retrieval`
supports a retrieval-off ablation.
Cards inherit their source split from the run; mismatching declarations and unlisted
source runs are rejected when writing reusable memory.

`tests/test_munin_integration.py` uses a synthetic ROT13 source solve and three distinct
synthetic target strings. A deterministic policy uses one tool action with retrieval and
two without retrieval in each trial. This validates split gating and transfer plumbing;
it is a mechanism test with fixed policies, not a model experiment, statistical claim,
or evidence of improved live challenge performance. Evaluation split labels are supplied
by intake metadata and are not cryptographically enforced against a mislabeled run.
