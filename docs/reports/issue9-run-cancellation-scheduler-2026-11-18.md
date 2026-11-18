# Issue #9: run cancellation and specialist scheduling

2026-11-18。run全体を `codex cancel RUN_ID` で取消しても、schedulerがjob状態だけを
見て新しいspecialistやmodel turnを開始できる経路を修正した。

## 実装

- enqueue・retry・slot予約・host起動・model-turn予約でrun取消状態を確認する。
  model-turn予約とhost起動の確認はrun lockで取消と直列化する。
- `tick` とspecialist driverはrunの取消状態を独立に読み、既存jobを取消へ反映する。
  停止未確認のhostは `unknown` としてslotを保持し、明示releaseを必要とする。
- Codex実行中のstop callbackもrun状態を確認する。取消後の返答・report・intent結果を
  commitせず、既に予約したmodel turnは返却しない。
- `tick` のreport拒否処理はattemptとrunning状態を再確認する。遅延reportが
  completed・cancelled・timed_out状態や置換済みattemptをfailedへ上書きしない。

## 検証

実行コマンド:

```sh
.venv/bin/pytest -o addopts='' -q tests/test_agent_orchestration.py tests/test_codex_specialist.py tests/test_agent_autopilot.py tests/test_intent_identity.py tests/test_agent_benchmark.py
```

104件すべて成功、exit code 0。分割取得した出力を連結:

```text
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 15.65s
```

新しい回帰検査は、取消後のrun指定/global dispatch、enqueue/retry拒否、予約後spawn前の
取消、model-turn消費維持、provider呼出前の取消、実行中stop callback、遅延出力拒否、
停止未確認slotの保持、遅延reportとterminal/置換attemptの競合を確認する。
既存の偽Codex subprocess試験もassignment取消とrun全体取消の両方で実行し、
ハングするローカルプロセスが15秒以内に停止して予約1回を保持することを確認した。
実provider・外部CTFへの呼出やsubmissionは行っていない。

assignment単位の取消では他のrunning jobを維持することを追加で明示検査した:

```sh
.venv/bin/pytest -o addopts='' -q tests/test_codex_specialist.py::test_cancelled_or_stale_attempt_stops_the_driver
```

```text
.                                                                        [100%]
1 passed in 0.20s
```

`stop_outcome` の `cancel_run` 呼出はrun全体が取消状態のときだけ動作し、通常の
assignment取消ではno-opとなる。追加検査はexit code 0。

最終監査では `complete`・`intent`・`candidate` がすべてrun lock内で `_running` の
run取消チェックを通ることを確認した。`complete` の既存回帰検査に加え、取消後かつ
tick前のrunning jobへ直接intent/candidateを渡す試験を追加した。intentは実行関数を
呼ばず、action予約・intent開始記録・turn消費を増やさない。candidateはprivate file・
database行・受信記録を作らない。上記103件に含めて成功している。

slot予約後・host起動前のassignment/wave取消もrun lock解放後のbarrierで検査した。
dispatchはhost起動lock内でattempt一致とrunning状態を再確認し、取消済みattemptを
起動しない。`_stop` は同じlock内で現在のhost identityを再取得し、未起動なら停止確認済み
としてcancelledへ進める。retry予約時は前attemptのhost identityを消去する。
fresh/retry × assignment/waveの4ケースで、取消後のspawn・host identity保存・不要な
host cancelが発生しないことを検証した。停止済みか不明な実hostの既存unknown契約は維持する。

deadline処理も同じ境界で直列化した。tickはrun lock内でattempt・running状態・現在のdeadlineを
再確認し、host停止からtimed_out保存までlockを保持する。dispatchは起動lock内で予約の期限を
確認し、期限切れならhostを起動せずtimed_outへ進める。追加のbarrier試験はtickが停止確認後に
一時停止している間、dispatchが同じlockを越えられず、timeout確定後もspawnしないことを確認した。
brief生成が遅れて期限を超えた場合もspawn前に再検査して拒否する。予約情報には新attemptの期限を
反映し、retry時に前attemptの期限を誤用しない。試験で予約後の期限切れ、brief生成中の期限切れ、
timeout停止中のlock保持を確認した。

## 適用範囲

host adapterの停止確認は既存契約に従い、scheduler jobの整理は次のtick/操作または
specialist driver停止処理で行う。CodexCLIの実行中停止確認周期は従来の約2秒。
この変更は `codex_session.py` と `ctf_sandbox.py` を編集していない。
