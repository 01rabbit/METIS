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

## 証拠の読み取り（オフライン）

ログやインシデントの証拠を、上限付きで構造化して読む。結果は観測であり、判定ではない。
どの読み取りも `complete_for_input`（入力を最後まで読めたか）と `limitations`（言えないこと）を返す。

| 成果物ツール | CLI の種別 | 対象 | 主な出力 |
| --- | --- | --- | --- |
| `email` | `email` | EML / MBOX | 全ヘッダーの原文（中身の真偽は未検証として扱う）、MIME 部品の種類・ファイル名・復号後のハッシュ、構造の欠陥 |
| `browser_history` | `browser` | Chromium・Firefox の履歴 SQLite（WAL 付き） | 訪問・URL・ダウンロード、時刻の変換 |
| `json_records` | `json` | 厳密な JSON（重複キーは拒否、数値は字句のまま保持） | 型付きの値の木。`field` 指定時は直下フィールドの最大値（同値を全て保持） |
| `cloudtrail` | `cloudtrail` | CloudTrail の JSON | eventID ごとの重複・矛盾、認証・操作の結果、期間の絞り込み |
| `evtx_xml` | `evtx-xml` | `wevtutil` / EvtxECmd の XML 出力 | EventID、Provider、SystemTime、EventData の名前と値 |

- run の成果物には、専門家の intent（`kind: artifact`）か `metis codex artifact` で使う。上限は 8 MiB、
  既定のレコード数は 200（`max_records` で 10,000 まで）。
- ローカルのファイルには `metis evidence KIND FILE [--since ... --until ...] [--out .metis-state/x.json]`。
  `--out` は `.metis-state/` 配下の新しいファイルだけに書く（上書き・シンボリックリンク経由は拒否）。
- バイナリの EVTX、メモリイメージ、ディスクイメージは対象外。外部ツールで XML などに変換してから読む。

## SIEM の検索（`metis siem`）

Blue Team CTF で Splunk や Elasticsearch の読み取り権限が配られた場合に使う。自由な検索言語は受け付けず、
索引・期間・等値フィルター・列・件数だけを指定する。プロファイル（例: `configs/blue/siem.example.json`）で、
接続先、トークンを読む環境変数、使ってよい索引と列、件数と期間の上限を決める。

```sh
metis lease task RUN hunt-1 splunk=1                       # Daybreak がタスクに枠を貸す
metis siem search --run RUN --task hunt-1 --profiles configs/blue/siem.json \
  --profile splunk-read --request request.json             # 結果は stdout の JSON
metis lease finish RUN hunt-1                              # 停止を確認できていれば枠を返す
```

- Splunk はジョブを作ってページ単位で読み、最後に終了を確認する。Elastic は1回の `_search`
  （`allow_partial_search_results=false`）。リダイレクトとプロキシは使わず、HTTP は loopback の試験用だけ。
- 応答は 2 MiB まで。重複キー、NaN、極端な数値を含む JSON は拒否する。返った値もトークンや
  `password=` の形を伏せる。
- `complete` は、件数上限・短いページ・部分結果・不正確な総数のどれにも当たらない場合に限る。
  中止の応答だけでは止まったとみなさない（`indeterminate`）。止まったと確認できるまで枠は返らず、
  `metis siem reconcile --connection-id ...` で状態を確かめてから `lease finish` する。

## 接続プロファイル（`metis connect`）

SSH の読み取り（`identity`、`system`、`processes`、`sockets`、`os-release`、許可したログの `read-log`）、
RDP・VNC のデスクトップ、SOCKS、OpenVPN を、プロファイル（例: `configs/blue/connections.example.json`）
から起動する。既定は起動計画の表示だけで、`--execute` を付けたときだけ起動する。

- SSH はホスト鍵を厳格に確認し、エージェント転送やローカルコマンドを無効にする。パスワードは環境変数経由、
  RDP のパスワードは標準入力で渡し、引数に置かない。RDP は証明書の SHA-256 を固定するか拒否する。
- OpenVPN の設定は、デーモン化・外部スクリプト・管理ポートなどの指示を含むと拒否する。
- RDP の操作、VNC の `control`、SOCKS と VPN の `start` は外部の状態を変えうるため、`metis permit` の
  完全一致の許可が要る。許可の発行には所有者鍵が要る（Daybreak が `metis permit init` を一度実行する）。クライアントは独自のプロセスグループで動かし、終了時はグループごと止める。
- 出力は最後の 1 MiB だけを残し、環境変数経由の秘密と資格情報の形を伏せる。
- `scripts/connection_lab.py` は、使い捨ての Docker 環境（`tests/blue_lab/`）で SSH・RDP・VNC・SOCKS・
  VPN を実際に試す。生成した鍵は、停止を確認できた場合だけ消す。この環境では Docker が無いため未実行。

## 共有リソースとスコープ付き許可

[ORCHESTRATION_RUNTIME.md](ORCHESTRATION_RUNTIME.md) の「共有リソースとスコープ付き許可」を参照。
