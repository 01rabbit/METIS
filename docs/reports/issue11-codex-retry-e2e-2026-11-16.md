# Issue #11 実 Codex による重複制御・cancel の検証（2026-11-16）

PR #18 で入れた重複 intent の制御（正準化、再試験の上限、option 変種の上限）と、実行中の cancel を、
実 Codex 専門家で確かめた記録。合成 run を使い、flag は含まない。

## 条件

- main d0d6527（PR #18 マージ後）に `metis agent codex --note` を加えたブランチで実行した。
- 専門家は codex-cli 0.166.0、モデルは `gpt-daybreak-blue-latest`（active catalog の唯一の ID）。
- 合成 run `2ab1bdba…` に、HTML 3.0 KB・5 レコードの PCAP・1 KiB のバイナリの 3 ファイルを置き、
  run ごとに 3 slot を割り当てた。
- 実行時刻は 10:38:43〜10:40:43 UTC。
- Codex が自発的に重複や回避を試みるとは限らない。そこで Daybreak は `--note` で「この順に要求せよ」と
  手順を伝えた。note は brief とは別の Daybreak 発の文として表示されるが、intent の制御はすべて
  そのまま効く（単体テスト `test_daybreak_note_is_shown_but_cannot_widen_authority`）。

## 結果

attempt A（crypto 担当、`:2`）。要求は Codex が JSON で出し、METIS が判定した。

| 手順 | Codex の要求 | METIS の判定 |
| --- | --- | --- |
| 1 | text 00-page.html {offset 0, length 12000} | 実行、event 5 |
| 2 | 同じ要求で length 11999（ファイルは 3.0 KB） | 拒否: event 5 と同じ正準要求 |
| 3 | 手順 1 と同じ要求、new_evidence [1]（intake 時のイベント） | 拒否: event 5 と同じ。引用した証拠は前回より古い |
| 4 | hex 02-data.bin {offset 0, length 64} | 実行、event 9 |
| 5 | 手順 1 と同じ要求、new_evidence [9] | 実行（正当な再試験）、event 13 |
| 6 | 手順 5 と同じ要求 | 拒否: 再試験の上限 |

その後、報告を提出して completed になった。Codex のターンは 7 回。

attempt B（triage 担当、`:1`、A の完了後に実行）。

| 手順 | Codex の要求 | METIS の判定 |
| --- | --- | --- |
| 1 | pcap 01-q.pcap {packets 200} | 実行、event 17 |
| 2 | 同じ要求で packets 199（レコードは 5 件） | 拒否: event 17 と同じ正準要求 |
| 3 | A が実行済みの text 要求 | 拒否: 再試験の上限（A が既に 2 回実行） |

attempt C（forensics 担当、`:3`）は、Codex の 1 ターン目の最中に Daybreak が cancel した。
cancel は 10:38:59.693、`codex_killed` は 10:39:00.075 で、0.38 秒後に停止している。cancel の前に動いて
いた `codex exec` は 2 本（A と C）、3 秒後は 1 本だった。残った 1 本は A のターンで、A は 10:39:01.259 に
そのターンを完了している。

## 監査ログ

`agent_job_log` には、started 3、codex_turn 11（各 thread ID 付き）、`intent_duplicate` 5（拒否の理由と
引用すべき event 番号付き）、cancelled 1、codex_killed 1、completed 2 が残った。どの Codex ターンでも
ツール系 item や router の痕跡は出ていない。

## 判断

PR #18 のときに挙げた、修正後のコードで実 E2E を回していないという未確認事項は解消した。
次の 6 点を実 Codex で確認した。

- 同一要求の重複拒否
- option 変更による回避の拒否
- 無関係なイベント番号による回避の拒否
- 新しい証拠に基づく再試験が 1 回だけ通ること
- 実行中の cancel によるプロセス停止
- 監査ログへの記録

ただし、どれも Daybreak の指示に従った試験であり、Codex が自発的に回避を試みた場合の挙動を網羅した
ものではない。
