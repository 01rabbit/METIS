# 専門家AIオーケストレーションの実行層（Issue #11）

[CTF_ENVIRONMENT_AND_ORCHESTRATION.md](CTF_ENVIRONMENT_AND_ORCHESTRATION.md)（以下「仕様」）の
P1〜P5 を実装した結果と、使い方・互換性・残る制約をまとめる。

## 1. 構成

| 層 | モジュール | 役割 |
| --- | --- | --- |
| P1 契約・policy | `core/agent_contracts.py` | `SpecialistProfile` `Assignment` `ModelSelection` `ExecutionRecord` `CompactReport` `WaveDecision`（すべて `extra=forbid`、有限値、schema_version 2）。`decide_wave` と `select_model` は純粋関数 |
| 計画・台帳 | `core/ctf_orchestration.py` | `plan_agent_wave(context, force_mode=)` は決定的。`AgentLedger` は wave と compact report の台帳 |
| P2 ホスト | `core/agent_host.py` | `capabilities / spawn / poll / send / cancel / collect`。`BridgeHost`（既定）、`SequentialHost`、テスト用 `FakeHost` |
| P3 scheduler | `core/agent_scheduler.py` | slot予約、attempt、deadline・max turns、cancel/retry/release、tool intent の仲介 |
| 単一writer | `core/run_lock.py` | run ごとの排他ロック。予算予約・イベント追記・公式提出をこの下で行う |
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

### tool intent（担当 → controller）

```json
{"kind": "artifact", "tool": "text", "artifact": "00-cipher.txt", "options": {}}
{"kind": "data", "tool": "base64_decode", "data": "aGVsbG8="}
```

- `kind` は `data` / `artifact` / `derive` のみ。`submit` `attest` `grant` `auth` `remote` `web` `sandbox`
  `delegate` `extend` は「Daybreak 専用」として拒否し、ログに残す。
- 同じ run で同じ action identity（tool・入力 digest・options・artifact）の再実行は拒否。新しい証拠の
  イベント番号を `new_evidence` に挙げた再試験だけ許す。
- 実行は run lock の下で `CodexSession` を通るため、予算超過・イベント番号衝突は起きない。
- 1 intent = 1 turn。`max_turns` を超える要求は拒否し、その attempt を `timed_out` にする。

### 状態と attempt

`queued → running → completed | failed | cancelled | timed_out`、停止を確認できない場合は `unknown`
（slot を占有したまま。`metis agent release ASSIGNMENT_ID` で確認後に解放）。
再実行（`agent retry`）は新しい attempt を作り、最大3回。古い attempt の intent・報告は拒否して監査ログ
（`agent_job_log`）に残る。

### slot

同時実行数 = `min(ホストの上限, 全体slot, run ごとのslot, wave の担当数)`。
`metis agent slots --global 4 --per-run 2` で設定（既定 4 / 2）。足りない分は `queued` のまま。
大会の `max_parallel`（同時に着手する問題数）とは別の上限で、両方が効く。

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
