# Blue Team 機能

METIS は CTF の自動解答を主目的にしてきたが、DEF CON Blue Team Village CTF のような防御側の課題
（ログ・ホスト・ネットワーク・メール・クラウドの証拠を調べて答える形式）や、attack-defense の防御作業にも
同じ統制で対応するため、SOC 調査用の Blue Team 機能（METIS Blue）を加えた。
この文書は、取り込んだ機能の使い方と境界をまとめる。

## ケース記録（`metis journal`）

調査の観測・検索・所見・教訓を、run とは別の私有ディレクトリ（既定 `.metis-state/journal`、
`--root` か `METIS_JOURNAL_ROOT` で変更）に残す。ディレクトリは 0700、ファイルは 0600 で作る。

```sh
CASE=$(metis journal open --case "beacon alert" --type ctf --objective "C2 の宛先を特定する")
metis journal query   --case "$CASE" --platform zeek --query "conn.log を宛先で集計" --hits 3
metis journal finding --case "$CASE" --summary "60 秒周期の通信" \
  --evidence "conn.log 10.0.0.5 -> 198.51.100.7:443" --confidence high
metis journal close   --case "$CASE" --outcome solved --summary "周期通信を確認"
```

- 種別は `incident / hunt / ctf / training / detection / intel`、確度は `high / medium / low / unproven`。
- 所見の `--evidence` には、証拠のファイルと場所を8文字以上で書く（根拠のない所見を残さない）。
- 入力に資格情報の形（秘密鍵、AWS キー、Bearer、JWT、GitHub/Slack トークン、Cookie ヘッダ、`password=`）や
  METIS の答えの形（`flag{...}` などの例示は除く）があれば、値を表示せずに拒否する。答えは答え保管庫へ。
- `close` は `case.md` の結果欄だけを機械的に書き換え、手で書いた本文は残す。`INDEX.md` を作り直す。

## リポジトリの検査（pre-commit）

`scripts/check_repo.py` は、Git に入る前に次を止める。値は表示せず、パスと規則だけを出す。

- 実行時の私有パス（`.metis-state/`、`*.sqlite`、`.env`、鍵ファイル、`answers.json` など）
- 秘密の形（秘密鍵、AWS・GitHub・Slack・OpenAI/Anthropic 形式のキー）
- 答えの形（テストと合成練習問題の生成器を除く）
- `--staged` では、ステージした内容と作業ツリーの差（確認した内容と違うものをコミットしない）
- `METIS_DENY_PATTERN` を設定すると、チーム名やホスト名などの私有の識別子も拒否する

clone ごとに一度 `git config core.hooksPath .githooks` を実行すると、コミット時に自動で走る。CI でも全体を検査する。

## 共有リソースとスコープ付き許可

[ORCHESTRATION_RUNTIME.md](ORCHESTRATION_RUNTIME.md) の「共有リソースとスコープ付き許可」を参照。
