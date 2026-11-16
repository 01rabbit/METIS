# Issue #28 ZipCrypto 解析ツール（2026-11-16）

## 調査（一次資料と既存実装）

- Stay, "ZIP Attacks with Reduced Known Plaintext"（FSE 2001）の 4 章を本文で確認した（著者のサイト math.ucr.edu/~mike/zipattacks.pdf）。
  - Info-ZIP は `srand(time ^ getpid())` を 1 回だけ実行し、各メンバーの 10 バイトの乱数を同じ初期状態で 2 回暗号化する。
  - そのため、ヘッダの先頭バイトは乱数のバイトそのものになる。5 ファイル以上あれば種が決まり、全ヘッダの乱数が分かる。
  - ただし既知平文にはならない（2 回の暗号化の鍵の流れの XOR しか分からない）。鍵の復元は約 **2^39** の暗号化の計算になる（論文では 500MHz の CPU で約 2 時間）。
- Info-ZIP zip 3.0 のソース（Debian の crypt.c と tailor.h）を確認した。`ZCR_SEED2` は Unix では `getpid()`（crypt.c の既定 3141592654 は使われない）。
- Stay の 2020 年の論文（ePrint 2020/983）は本文を取得できなかった（403）。概要では 2 ファイルで鍵を復元できるとしているが、計算量は確認できていない。
- 既知平文攻撃（Biham–Kocher）は、bkcrack（zlib ライセンス、Joachim Hotonnier）の Attack・Zreduction・各表を参照して移植した。

## 実装（`core/ctf_zipcrypto.py`、artifact tool 4 種）

| ツール | 内容 | 予算と失敗理由 |
| --- | --- | --- |
| `zipcrypto_info` | メンバー、チェックバイト、UT 時刻、Info-ZIP の漏洩バイト | なし |
| `infozip_seed{time_from,time_to,pid_bits,generator,seconds}` | glibc（TYPE_3）／MSVC の rand の種を `time^pid` または `time^π` から探し、全メンバーのヘッダの乱数 10 バイトを返す | 期間 31 日、`seconds` 300 以下。`no_seed_in_range`、`too_few_members`、`work_exceeds_budget` |
| `zipcrypto_attack{member,plaintext_hex,offset,seconds}` | Biham–Kocher。縮約は numpy、鍵の探索は numpy でベクトル化し、CPU コア数で並列 | 既知平文 12 バイト以上（8 バイト連続）。`not_enough_plaintext`、`work_exceeds_budget`、`no_solution` |
| `zipcrypto_decrypt{member,keys}`（derive） | 鍵で復号し、チェックバイトと CRC を検証して artifact として登録する | 鍵が誤っていれば理由を返す |

Stay の鍵復元（2^39）は実装していない。`infozip_seed` の結果に、その旨と計算量を明記している。

## 検証

- bkcrack 自身の攻撃テストのベクトル（"Hello World!" → 鍵 `ea9b4e4d/ba789085/5ff8707d`）と一致した。
- 実際の glibc（Debian、ctypes）の `rand()` の出力と、小さい種・大きい種の両方で一致した。移植の途中、`__srandom_r` の int32 の切り詰めを誤っていた不具合をこの照合で見つけて直した。
- 実際の Info-ZIP zip 3.0（Debian glibc 2.41）で作った 7 メンバーの zip（`tests/fixtures/infozip-glibc-vector.zip`、パスワード `testpass`、内容は合成の乱数）で、種を 1.7 秒で復元した。予測した 70 バイトの乱数は、パスワードで 2 段の暗号化を戻した値とすべて一致した。
- 既知平文攻撃: 60 バイトの既知平文で、正しい鍵を 145 秒・210 秒で復元した（15 ワーカー）。CI では、候補を絞ったパイプラインのテストのみを実行する。網羅的な探索は `METIS_TEST_SLOW=1` のときだけ実行する。
- 専門家 intent の合成テストは `zipcrypto_attack` → 同じ鍵で全メンバーを復号して CRC を検証 → encoded メンバーを `zipcrypto_decrypt` で導出 → XOR まで進む。これは真の key2 候補と decoys に縮小したテストで、探索空間全体の成功を示すものではない。実行: `.venv/bin/pytest tests/test_ctf_zipcrypto.py -q`。
- 極小の wall-clock 予算で `work_exceeds_budget` と `z-reduction` 段階の理由コードを返すテストを追加した。
- ksnctf #39: 種を 0.8 秒で復元した（7 メンバーすべて一致。`time ^ pid`）。鍵の復元には至らず、#39 は未解決のまま。

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
- 攻撃 worker の上限には wall-clock 秒と候補数の制限があるが、OS が強制するメモリ上限はまだない。メモリ枯渇時の管理された理由コードも未検証。
- 専門家 intent の合成試験は候補削減したパイプラインを確認するもので、通常の再現テストでは全候補探索からの鍵回復を証明していない。
