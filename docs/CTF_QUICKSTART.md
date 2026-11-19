# CodexでCTFを解くためのクイックスタート

## 1. 取得と準備

現在の実装は `metis-full-implementation` ブランチにあります。

```sh
git clone --branch metis-full-implementation https://github.com/01rabbit/METIS.git
cd METIS
python3 scripts/setup.py
./start
```

インストール済みのAI CLIを自動検出して起動します。Codex以外を選ぶ場合は
`./start --agent claude` のように指定します。AIが準備状態を確認し、問題URLまたは
ローカル配布ファイル、必要に応じてプラットフォームやchallenge IDを確認します。
METIS自体には別のモデルAPIキーもDockerも不要です。

Codexを選んだ場合、起動コマンドはDaybreakとマルチエージェント機能を有効にします。Daybreakが
全体を管理し、独立した解析だけを利用可能な下位モデルへ通常2〜4担当で並列化
します。単純作業には小さいモデルと必要最小限の文脈を使い、重複調査や目的の
ない大量起動を避けます。公式解答の送信と判定はDaybreakが一元管理します。
通常のローカル操作は自動承認レビューへ回し、進捗報告やサブエージェント完了の
たびには停止しません。対象範囲、認証、問題選択など、ユーザー入力なしでは
安全に決められない項目だけをまとめて確認します。

## 2. 問題を取得

標準的なCTFdの問題は次の形です。

```sh
.venv/bin/metis web open 'https://ctf.example/challenges' --adapter ctfd --challenge-id 12
```

一般的なHTML問題ページでは次の形です。

```sh
.venv/bin/metis web open 'https://ctf.example/problem/12' --adapter html
```

ksnctfの問題URLは標準の `--adapter auto` で自動認識し、URLから問題番号を
読み取ります。明示する場合は `--adapter ksnctf` を指定します。

```sh
.venv/bin/metis web open 'https://ksnctf.sweetduet.info/problem/2'
```

取得結果の `run_id` を使い、候補を標準入力から送信します。ksnctfでは同一
オリジンの `/api/submit` にJSONで送信し、HTTP 200とJSONの `result: true`
だけを正解とします。正解時は実行状態が `solved` になり、成功した手法を
`metis memory learn` で保存できます。文字列の `"true"`、埋め込みの正解表示、
転送先の応答は正解になりません。送信時のリダイレクトは追従しません。
以前 `--adapter html` で取得した実行は自動変更せず、新しく取得してください。

複数問題を扱う場合も、各問題は配布物込みの1つのrunとして取得します。同じ
問題を本文用と配布物用に二重登録しません。機械的デコード、アーカイブ/PCAP、
静的ソース、稼働サービスに分類して並列化し、根拠のある候補は他の問題を待たず
すぐ公式判定へ送ります。ksnctfで通信結果が不明になった同一候補は、送信上限の
範囲内で回復再送できます。

同一オリジンの一般的な配布ファイルは自動取得されます。別の配布用オリジンは、
大会が明示したものだけを `--allow-origin` で追加します。ログインが必要な場合、
トークンやCookieは `metis web auth` のマスク入力か既存の環境変数を使います。
同じオリジンで再認証すると、同じ値でも以前の保存資格情報とセッションCookieを置き換えます。
値を会話やコマンド引数へ貼り付けません。

保存済み資格情報の利用を止める場合は、同じオリジンの記録を削除します。
この操作はMETISのローカル利用を止めるだけで、CTFサービス側のトークンを失効しません。
SQLiteの物理消去やWAL・バックアップからの消去も保証しません。

```sh
.venv/bin/metis web forget 'https://ctf.example'
```

### rCTFとJavaScript描画ページ

rCTFではチームトークンをマスク入力で一度だけ渡し、派生したBearer認証トークンだけを
保存します。問題IDは文字列です。

```sh
.venv/bin/metis web auth 'https://ctf.example' --kind rctf-team-token
.venv/bin/metis web catalog 'https://ctf.example' --adapter rctf
.venv/bin/metis web open 'https://ctf.example' --adapter rctf --challenge-id baby-rsa
```

問題文がJavaScriptで描画されるページは `--render` を付けます。事前に
`python3 scripts/setup.py --browser` でPlaywrightとChromiumを入れてください。
許可オリジン外へのブラウザ通信はすべて遮断され、結果に記録されます。

### nc接続の問題（リモートサービス）

問題文の `nc host port` は候補にすぎません。許可された接続先だけを登録します。

```sh
.venv/bin/metis remote suggest RUN_ID
.venv/bin/metis remote grant RUN_ID chall.example.org 31337
.venv/bin/metis remote exchange RUN_ID 0 --script steps.json
.venv/bin/metis remote pipe RUN_ID 0 -- python3 .metis-state/work/solver.py
```

接続先の `0` は番号のほか、`host:port` や `latest`（最後に許可した有効な接続先）でも指定できます。
問題インスタンスを起動し直してポートが変わったときは `remote grant ... --replace` で登録すると古い接続先は
無効になり、`latest` で新しい方につながります。`metis remote list RUN_ID` で一覧を確認できます。

`exchange` は送受信ステップのJSON、`pipe` は自作ソルバーの標準入出力を
ソケットへ中継します。受信データは run の成果物として保存され、静的解析
ツールで調べられます。

### SSH問題とWeb問題のサーバー

SSHでログインする問題も同じ `remote grant` で接続先を登録し、問題文のパスワードを
標準入力から渡してコマンド実行やファイル取得をします（ホスト鍵はrunごとに初回固定）。

```sh
printf '%s\n' 'PASSWORD' | .venv/bin/metis remote ssh RUN_ID 0 --user q4 --password-stdin --command 'ls -la'
printf '%s\n' 'PASSWORD' | .venv/bin/metis remote ssh RUN_ID 0 --user q4 --password-stdin --get /home/q4/q4
```

問題ページと攻撃対象のWebアプリが別オリジンの場合は、許可されたアプリのオリジンを
runへ追加してからリクエストします。cookieはrunごとに保持されます。

```sh
.venv/bin/metis web grant RUN_ID https://chall.example.org
.venv/bin/metis web request RUN_ID https://chall.example.org/login --method POST --form "user=admin' --" --form pass=x --follow
.venv/bin/metis web request RUN_ID --batch requests.json   # 最大256件を1アクションで（ブラインドSQLiなど）
```

### Claude Codeのsandbox内で使う場合

METISのネットワーク系コマンド（`web`、`remote`）は、`ALL_PROXY`／`HTTPS_PROXY` の
プロキシを自動で経由します。sandbox内では生のソケットや名前解決が使えませんが、
この経路なら通ります。`.venv/bin/metis doctor` の `network_route` で経路を確認できます。
接続先ホスト（例: 問題サーバー）はsandboxのネットワーク許可リストに追加してください。
sandboxの外で実行する必要はありません。

### 時間予算と中断からの再開

runの制限時間は、取得時ではなく最初の操作から数えます。期限切れ（`exhausted`）に
なったrunは、作り直さずに `metis codex extend RUN_ID --seconds 3600` で再開します。
複数問題を扱うときは `metis contest` のキューで残り問題を管理し、新しいセッションでは
`metis contest board` と `metis codex board` から続きを再開します。

### WriteUPとナレッジの蓄積

大会ごとに `writeups/<大会名>/` を作り、問題ごとのWriteUPをMarkdownで保存します。
正解したら、エージェントが本文（概要・解析・解法・flag・学び・スクリプト・手法）を
JSONで渡して `metis writeup save CONTEST_ID 問題番号 --file entry.json` を実行します。
METISが提出履歴、仮説の変遷、配布ファイルのSHA-256、接続先、所要時間を自動で追記し、
大会ごとの一覧（`writeups/<大会名>/README.md`）と、大会をまたいだ手法集
（`writeups/KNOWLEDGE.md`）を更新します。手法は技術カードとしても保存され、
次の問題の取得時に似た手法として提示されます（技術カードにはflagを入れません）。
WriteUPが未作成の解決済み問題は `metis writeup missing CONTEST_ID` で確認できます。

### 動的解析（サンドボックス）

配布バイナリはホストで実行せず、隔離コンテナでのみ実行します。Docker Desktop、
OrbStack、Colima、Podmanのいずれかを用意し、一度だけイメージを作成します。

```sh
.venv/bin/metis sandbox build          # 既定はホストCPU向け（Apple Siliconなら arm64）
.venv/bin/metis sandbox run RUN_ID ARTIFACT --stdin-file in.bin
.venv/bin/metis sandbox run RUN_ID ARTIFACT --mode gdb --gdb 'run < /work/.stdin' --gdb 'bt'
.venv/bin/metis sandbox run RUN_ID ARTIFACT --with LIBC --mode script --script exploit.py
```

コンテナはネットワークなし、読み取り専用ルート、ホストのマウントなし、権限なし
ユーザー、CPU・メモリ・プロセス数制限で起動します。script モードでは pwntools が
使えます。イメージはホストCPU向けに作られ、別アーキテクチャのELF（Apple Silicon上の
x86-64など）は自動でQEMUユーザーモード実行になります。その場合 gdb はQEMUのgdbスタブ
経由（`run` は自動で `continue` に置換）、strace は `qemu -strace` で動き、ltrace は
使えません。scriptモードでは `$METIS_RUNNER`（例: `qemu-x86_64 -L /usr/x86_64-linux-gnu`）
を対象の前に付けて実行します。エミュレーション下のスタックやlibcの絶対アドレスは
実機と異なるため、オフセットの確認に使い、絶対アドレスはリモートでリークしてください。

### Claude Codeで使う

`integrations/claude-code/README.md` の手順で `.claude/` へ一度コピーした後、`./start --agent claude` で起動すると、`CLAUDE.md`、`.claude/skills/metis`、
`.claude/agents/ctf-*`（カテゴリ別サブエージェント）、`/ctf` コマンドが使えます。
`metis plan` の各担当は対応する `ctf-*` サブエージェントへ並列に割り当てられ、
公式送信はメインセッションだけが行います。

## 3. 解答と自己修正

Codexはファイル形式を確認し、制限付きの解析ツールで根拠を集めます。抽出した
文字列はまだ正解ではありません。候補は公式CTFd API、ksnctf JSON API、または結果条件を明示設定
したHTMLフォームへ送信し、公式の正解判定だけを成功として扱います。

不正解なら同じ候補を再送しません。公式フィードバックと観測結果から失敗理由、
修正仮説、次の判別手順を記録し、新しい候補へ進みます。送信回数の上限と
`Retry-After` を守ります。中断した実行は同じDBから再開できます。

正解後は、フラグや秘密情報を除いた「使えた方法」「適用条件」「失敗理由」を
MUNINへ保存します。次の問題では関連する知識が検索されますが、現在の証拠に合う
かを確認してから利用します。

## 安全上の境界

配布バイナリやスクリプトをホスト上で実行しません。現状は静的解析が中心です。
動的pwn、ブラウザJavaScript必須ページ、独自APIには、別途強制隔離された実行環境
または追加アダプターが必要になる場合があります。その場合も、確認できていない
候補を正解とは報告しません。
