# Issue #28 ZipCrypto 解析ツール（2026-11-16）

## 調査（一次資料と既存実装）

- Stay, "ZIP Attacks with Reduced Known Plaintext"（FSE 2001）の 4 章を本文で確認した（著者のサイト math.ucr.edu/~mike/zipattacks.pdf）。
  - Info-ZIP は `srand(time ^ getpid())` を 1 回だけ実行し、各メンバーの 10 バイトの乱数を同じ初期状態で 2 回暗号化する。
  - そのため、ヘッダの先頭バイトは乱数のバイトそのものになる。5 ファイル以上あれば種が決まり、全ヘッダの乱数が分かる。
  - ただし既知平文にはならない（2 回の暗号化の鍵の流れの XOR しか分からない）。鍵の復元は約 **2^39** の暗号化の計算になる（論文では 500MHz の CPU で約 2 時間）。
- Info-ZIP zip 3.0 のソース（Debian の crypt.c と tailor.h）を確認した。`ZCR_SEED2` は Unix では `getpid()`（crypt.c の既定 3141592654 は使われない）。
- Stay の 2020 年の論文（ePrint 2020/983）は本文を取得できなかった（403）。概要では 2 ファイルで鍵を復元できるとしているが、計算量は確認できていない。
- 既知平文攻撃（Biham–Kocher）は、bkcrack（zlib ライセンス、Joachim Hotonnier）の Attack・Zreduction・各表を参照して移植した。

## 実装（`core/ctf_zipcrypto.py`、artifact tool 5 種）

| ツール | 内容 | 予算と失敗理由 |
| --- | --- | --- |
| `zipcrypto_info` | メンバー、チェックバイト、UT 時刻、Info-ZIP の漏洩バイト | なし |
| `infozip_seed{time_from,time_to,pid_bits,generator,seconds}` | glibc（TYPE_3）／MSVC の rand の種を `time^pid` または `time^π` から探し、全メンバーのヘッダの乱数 10 バイトを返す | 期間 31 日、`seconds` 300 以下。`no_seed_in_range`、`too_few_members`、`work_exceeds_budget` |
| `zipcrypto_attack{member,plaintext_hex,offset,seconds}` | Biham–Kocher。縮約は numpy、鍵の探索は numpy でベクトル化し、CPU コア数で並列 | 既知平文 12 バイト以上（8 バイト連続）。`not_enough_plaintext`、`work_exceeds_budget`、`no_solution` |
| `zipcrypto_stay_scan{random_header_bytes_hex,start,stop,max_candidates,seconds,max_hits}` | Stay Stage 1 の40-bit探索を固定Cフィルタで実行。候補ID/carry maskはprivate shardへ保存 | 5–64メンバー、秒数10–300、候補/ヒット上限あり。隔離実行できない場合はfail closed |
| `zipcrypto_decrypt{member,keys}`（derive） | 鍵で復号し、チェックバイトと CRC を検証して artifact として登録する | 鍵が誤っていれば理由を返す |

Stay の Stage 1 partial-state search はMETISの隔離workerで実行できる。鍵復元（約2^39の後続処理）は未実装。`infozip_seed` の結果に、その旨と計算量を明記している。

## 検証

- bkcrack 自身の攻撃テストのベクトル（"Hello World!" → 鍵 `ea9b4e4d/ba789085/5ff8707d`）と一致した。
- 実際の glibc（Debian、ctypes）の `rand()` の出力と、小さい種・大きい種の両方で一致した。移植の途中、`__srandom_r` の int32 の切り詰めを誤っていた不具合をこの照合で見つけて直した。
- 実際の Info-ZIP zip 3.0（Debian glibc 2.41）で作った 7 メンバーの zip（`tests/fixtures/infozip-glibc-vector.zip`、パスワード `testpass`、内容は合成の乱数）で、種を 1.7 秒で復元した。予測した 70 バイトの乱数は、パスワードで 2 段の暗号化を戻した値とすべて一致した。
- 既知平文攻撃: 60 バイトの既知平文で、正しい鍵を 145 秒・210 秒で復元した（15 ワーカー）。CI では、候補を絞ったパイプラインのテストのみを実行する。網羅的な探索は `METIS_TEST_SLOW=1` のときだけ実行する。
- 2026-11-17 のslow direct-API testをseed付き合成ZIPへ拡張した。`METIS_TEST_SLOW=1 .venv/bin/python -m pytest -v tests/test_ctf_zipcrypto.py::test_full_known_plaintext_attack` は `1 passed in 17.05s`。8 workerで実候補探索から鍵を復元し、known/encoded両メンバーの平文とCRCを検証した。
- Specialist intent の高速テストは真の key2 候補とdecoysに縮小して確認する。別のslowテスト `METIS_TEST_SLOW=1 .venv/bin/python -m pytest -v tests/test_ctf_zipcrypto.py::test_specialist_intents_full_search_decrypt_and_xor` は、候補を差し替えず `zipcrypto_attack` intentで探索し、復元鍵を `zipcrypto_decrypt` intentへ渡し、text/XOR intentまで進んでいた。親プロセスの期限付きworker回収を追加した後、direct APIとintentの両slowテストを連続実行して `2 passed in 125.77s`。これはMETIS controllerのintent経路を呼ぶ決定的なscripted testであり、モデル自身がintentを選んだ実行ではない。
- 候補workerが1件の処理を終えない場合、親プロセスが残り時間でpoolをterminateするテストを追加した。`.venv/bin/python -m pytest -v tests/test_ctf_zipcrypto.py::test_attack_parent_kills_worker_when_candidate_exceeds_time_budget` は `1 passed in 0.69s`。通常のZipCrypto test moduleは `12 passed, 3 skipped in 10.30s`（slow/external-data tests skipped）。この期限はreduction反復とworker待ちを制限するが、候補配列の生成やPool起動を別プロセスから監督するhard end-to-end timeoutではない。
- 2026-11-17 に `zipcrypto_attack` を専用の固定worker routeへ接続した。攻撃本体・NumPy table初期化・全8 workerを同一コンテナ内へ置く。routeは固定 `zipcrypto` profile（2 GiB memory/swap上限、4 CPU、private IPC、network none、host mountなし、read-only root、unprivileged user）を使い、コンテナ内で有限の memory/swap/CPU/PID上限と読み取り可能な `memory.events` を確認してから処理する。sandbox未設定または確認失敗時はホストfallbackせず失敗する。専用imageには `numpy>=2,<3` を追加した。
- seeded合成ZIPの完全なMETIS intent連鎖をこの固定route内で実行し、全探索で鍵を復元、2メンバーのCRC/平文を検証、`zipcrypto_decrypt` と XOR まで成功した: `METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b METIS_TEST_SLOW=1 .venv/bin/python -m pytest -v tests/test_ctf_zipcrypto.py::test_specialist_intents_full_search_decrypt_and_xor` → `1 passed in 34.27s`。別の有効な合成キー/既知平文では300秒上限に達した。これは決定的controller intent testであり、モデルがintentを選択した試行ではない。
- 実機の期限テストでは `seconds=1` で `work_exceeds_budget` を返し、期限後にコンテナが残らないことを確認した。sandbox bootstrapは期限時に実行workerのプロセスグループ全体をSIGKILLする。一般sandboxの700 MiB割当テストでは512 MiB cgroup OOM markerを実測し、ZipCrypto routeの理由コード写像もunit testで確認した。
- 2026-11-17 にZipCrypto route自体のOOM結合テストを追加した。通常の2 GiB profileは変えず、テストからだけ指定できる固定128 MiB profileで本物のZipCrypto workerを合成ZIPに対して起動し、container OOMを `memory_limit_exceeded` として回収・分類する。テストは `.github/workflows/checks.yml` のsandbox jobで実行され、5件すべて成功した（`44001325425`: `5 passed in 76.78s`）。通常Python jobも `420 passed, 22 skipped in 79.92s`、Ruff/mypy/build/fixture validationを含め成功（runs `44001325425`, `44001331890`, `44001331898`）。OOMが起動/NumPy初期化/候補探索のどこで発生したか識別するphase markerはないため、reasonのstageは誤帰属を避けて `sandbox-oom` とする。これはroute統合の分類証拠であり、通常2 GiB profileでの候補探索由来OOMを示すものではない。
- 2026-11-17 に通常2 GiB ZipCrypto profile自体のcgroup OOM分類・後始末テストを追加した。合成ZIPをintakeし、network/host mountなしのprofile内で、まず `memory.max` / `memory.swap.max` が有限かつ上限以下と `memory.events` の存在を確認してからページをtouchする合成メモリ圧力を実行する。あわせて要求・返却resource profileが `zipcrypto` であることを確認し、`memory_limit_exceeded`、route mapperの `sandbox-oom`、worker registry削除を検証した。`.venv/bin/pytest -ra tests/test_ctf_zipcrypto.py::test_zipcrypto_production_profile_oom_classification_and_cleanup` → `1 passed in 1.31s`。exact HEAD `5858577e9b58b21a9c2d4bb29fee736798da7332`のsandbox CIは `6 passed in 86.27s`（run `44025607567`）。これは本番profileの上限・reason mapping・cleanup経路の証拠であり、ZipCrypto候補探索が自然にOOMになることを示すものではない。Stay回復とOOM phase attributionは引き続き未達。
- 2026-11-17 の追加修正で `Sandbox.execute` は container create / engine attach / workload result / OOM inspection の現在段階を保持し、engine timeoutをworkload timeoutと区別する。ZipCrypto routeはin-container supervisorが返すworkload timeoutだけを `work_exceeds_budget` とし、engine timeoutは段階付き `worker_failed` に分類する。`tests/test_ctf_sandbox.py::test_zipcrypto_engine_timeouts_are_distinct_from_workload_deadline` はcreate・attach・inspectionの各ケースをfake engineで検証。実container上で期限終了、OOM分類、プロセス群停止を含む追加4-test runも成功した。
- ksnctf #39: 種を 0.8 秒で復元した（7 メンバーすべて一致。`time ^ pid`）。鍵の復元には至らず、#39 は未解決のまま。

## 2026-11-18 update

- `zipcrypto_stay_scan` は最大4 CPU/2 GiBの隔離profileでのみ探索し、候補は`.metis-state/private-stay/`に0600で保持する。合成Info-ZIPベクタの実サンドボックス試験で埋め込み候補と全carry masksの一致を確認した。
- 公式#39の7メンバーからseed/header列を復元し、隔離native workerで40-bit Stage 1全域（2^40）をbounded chunksに分けて走査した。360件のStage 1候補をprivate shardに保存。共有key1 carry intervalで再評価したところ、88 interval recordsが残り、そのinterval幅の合計はcarry choices間の重複排除前で98,222,960。これは後続探索の入力に過ぎず、鍵復元ではない。Stage 2、復号、鍵に基づくCRC検証、公式提出は未実施で、#39は未解決。

## 実 Codex の測定（ksnctf #39、新しい DB、note なし、codex-cli 0.169.0）

| 指標 | 値 |
| --- | --- |
| 専門家の起動 | 4 |
| Codex のターン | 15（一時エラーによる再試行 4 を含む） |
| トークン | 152,281 / 2,634 |
| 実行時間 | 477 秒 |
| Daybreak の解析作業 | 0（scope の承認 1: `split_flag.php` の取得） |

- crypto 担当は `zipcrypto_info` → `infozip_seed` を自分で選んだ。ただし `pid_bits=16`、`seconds=2` と小さく指定したため、種が見つかった時刻の範囲を外したと見られる（推測です）。その後、Codex のターンがタイムアウトして失敗した。critic も `zipcrypto_info` を選んだ。web 担当は hardware key エラー（#24）で失敗した。
- Codex CLI が 0.166.0 から 0.169.0 に自動更新され、版の確認によって起動が拒否された（fail closed）。`codex-probe --ping` で、隔離のセルフテスト・ping・spawn カナリアが通ることを確かめてから、試験済みの版に加えた。

## 未達（#28 は Open のまま）

- Stay の鍵復元（2^39）。ネイティブ実装と `metis sandbox` での実行が必要。
- `max_candidates` は `z_reduction` 後に適用されるため、reduction中のpeak allocationを候補数だけでは制限しない。専用cgroup上限がプロセス全体の最終防衛線となる。自然な候補探索でのOOMは未確認。
- Stay key recovery（ksnctf #39 の目的）は未実装で、#28 は引き続きOpen。

## 2026-11-17 OOM phase attribution increment

The ZipCrypto worker now emits only allowlisted progress markers: `worker-imports`, `worker-startup`,
`archive-parsing`, `candidate-reduction`, and `candidate-key-search`. The bounded
sandbox wrapper preserves the last marker emitted before an OOM or timeout. The
stable reason remains `memory_limit_exceeded` with stage `sandbox-oom`; the
additional `phase` is coarse diagnostic evidence and does not imply a successful
search or identify a specific allocation site. Attribution is best-effort: an OOM
that kills the sandbox supervisor itself may return no worker phase.

Validation on the configured immutable linux/arm64 test image:

```text
METIS_TEST_SANDBOX_IMAGE=sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b \
METIS_TEST_SANDBOX_PLATFORM=linux/arm64 .venv/bin/pytest -ra \
  tests/test_ctf_zipcrypto.py::test_zipcrypto_real_low_memory_container_reports_memory_limit \
  tests/test_ctf_zipcrypto.py::test_zipcrypto_production_profile_oom_classification_and_cleanup
2 passed in 2.24s
```

The low-memory ZipCrypto worker test confirmed a recognized phase accompanies
the OOM reason, and the production-profile test still confirmed cgroup
classification and worker cleanup. A deterministic unit test checks marker
allowlisting and last-phase selection. This does not show a natural search
reaching the production memory limit. Issue #28 remains open for Stay key
recovery and the ksnctf #39 solve.

## 2026-11-18 Stay inverse-search review

The official #39 archive was reanalyzed in replacement run
`84525abb24d54f6cb9f235afec1eb9f7`. The bounded Info-ZIP seed operation
matched all seven leaked first header bytes. This confirms a PRNG hypothesis;
the seed and regenerated bytes are not known plaintext and do not establish
ZipCrypto keys, successful member decryption, or a solve. No candidate was
submitted.

Two independent expert reviews derived the byte-three forward recurrence for
both encryption passes and the differential filter. The bit count can
plausibly reconcile: section 3's 27 additional guesses include one carry,
whereas section 5's "same 26 bits" can mean the non-carry guesses, followed by
two pass-specific carry bits. The paper does not spell out that bookkeeping,
so the reconciliation is plausible, not certain. From the recurrence, each
carry guess gives an exact inclusive interval for the low 24 bits of the
multiplied initial `key1`; intersecting those intervals is implementable. A
new bounded helper and reduced-width exhaustive oracle test this interval
operation. The paper's claim that about 2^8 `key1_0` values survive is still
only an expected size: it gives no interval construction or measured size
distribution. Full candidate lifting, cross-file survivor sets, and the
inverse search remain unimplemented and need an independent direct-cipher
oracle before a full search can be trusted.

Current evidence therefore still stops before Stay inverse search. The #39
key recovery and official verdict remain unmet; Issue #28 remains open.
