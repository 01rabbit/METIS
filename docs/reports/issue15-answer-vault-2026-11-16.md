# Issue #15 正解情報と解析知識の分離（2026-11-16）

## 方針

既存の writeup は削除せず、解析の記録として残す。正解の値（flag、受理された候補、その hex・Base64 表現）は
リポジトリ外の答え保管庫へ移し、writeup には `⟦answer:<ファイル>#<番号>⟧` という参照だけを残す。
Git の履歴は書き換えない。

## 実装

- `core/answer_vault.py`
  - 保管庫は `$METIS_ANSWER_VAULT`、既定は `~/.local/share/metis/answers.json`。ファイルは 0600、ディレクトリは 0700。
  - 書き込みは一時ファイルからの置き換えで行い、読み戻して照合する。照合に失敗した場合、writeup には一切手を付けない。
  - 同じキーに別の値が来ても上書きせず、`alternates` に追記する。
  - 答えとして扱う形式は、`FLAG_…`、`Alpaca{…}`・`FLAG{…}`・`flag{…}`・`CTF{…}`、既知の答えの hex と Base64（3 通りのバイト境界）。
    `FLAG_XXXXXXXX` や `Alpaca{...}` のような書式の例は答えとして扱わない。
- `metis writeup vault-migrate [--path P] [--apply]`: 既定は dry-run（件数だけを表示）。`vault-restore` は逆の処理。
- `metis writeup save`: flag、本文（概要・解析・解法・教訓）、手法欄、コピーしたスクリプトに含まれる答えを
  自動で保管庫へ移す。公式判定との照合結果（`flag_check`）は従来どおり writeup に残る。
- 評価の区分: `writeups/EVALUATION_SPLIT.json`（`metis writeup split`）。writeup のある問題は practice とし、
  heldout は空。`metis web open` は `evaluation` を返し、practice の問題では `independent_evaluation: false` とする。
- MUNIN: `TechniqueCard.evidence`（成功・失敗の根拠）を追加した。空欄なら METIS が run から記入する（成功なら
  公式判定 correct、失敗なら観測された失敗）。答えの形の文字列は従来どおり拒否する。`KNOWLEDGE.md` に「根拠」を出す。
- 過去の正解が専門家 AI に渡らないための手当て:
  - Codex 専門家はホームディレクトリを読めない（#16 の OS 隔離）。
  - Claude のサブエージェント定義と skill には、保管庫を読まないこと、practice の問題では該当する writeup を
    開かないことを明記した。
  - MUNIN は保管庫を参照しない。

## 移行の実施

- 対象は `writeups/` と `work_nd/`。dry-run の後に適用した。
- 保管庫へ移したのは 70 件で、そのうち 6 件は Basic 認証トークンや出力 JSON に含まれていた hex・Base64 形。
  変更したファイルは 63。
- 記録が失われていないことの確認: 変更後の 63 ファイルすべてについて、保管庫の値で参照を置き換えた結果が
  HEAD の内容とバイト単位で一致した（不一致 0）。`vault-restore` の dry-run でも、参照先の欠落は 0。
- ガード: `tests/test_answer_vault.py::test_repository_tracks_no_answers` は、`writeups`・`work_nd`・`docs`・
  `challenges` の追跡対象に答えが無いことを CI で検査する。値は表示せず、件数だけを示す。

## 限界

- 答えは Git の履歴には残っている。履歴の書き換えは方針として行っていない。
- 検出は形式（パターン）と既知の値の符号化に頼っている。画像の中の文字列、独自形式の答え、
  別の変換（XOR、ROT など）を通した形は検出できない。
- Claude のサブエージェントに対する手当ては指示であり、OS による強制ではない。保管庫はホーム配下にあり、
  Claude Code の権限設定で読み取りを拒否しない限り技術的には読める。
- 評価の区分は、writeup のファイル名から問題 ID を推定している。`web open` での照合は ksnctf だけに対応している。
