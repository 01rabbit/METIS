# 大規模CTFモード

一人で多数の問題を扱う場合、全問題を順番に深掘りしません。問題一覧を一つの
永続キューへ入れ、得点、推定時間、確信度、依存関係、カテゴリ分散から最大4件を
選びます。30分以内に有力な証拠が出なければ、blockerを残して別問題へ移ります。

CTFdでは問題一覧を取得できます。

```sh
.venv/bin/metis web catalog 'https://ctf.example' > /tmp/catalog.json
printf '%s' '{"name":"My CTF","format":"jeopardy","max_parallel":4}' \
  | .venv/bin/metis contest create
.venv/bin/metis contest add CONTEST_ID < /tmp/catalog.json
.venv/bin/metis contest dispatch CONTEST_ID
```

認証が必要なら、先に `metis web auth` のマスク入力を使います。担当のrun ID、
推定時間、確信度、状態は `contest update` へJSONで渡します。

```sh
printf '%s' '{"state":"candidate","confidence":0.8,"run_id":"RUN_ID"}' \
  | .venv/bin/metis contest update CONTEST_ID CHALLENGE_ID
```

正解後はリンクしたrunが公式にverified/solvedである場合だけ、
`official_verified:true` と `state:"solved"` を記録できます。得点やsolve数が
変わった場合も更新し、再びdispatchします。

Attack/Defenseでは形式を `attack-defense` にします。サービスがdown/degradedなら
攻撃作業より復旧確認が優先され、testing中のpatchには回帰確認が割り当てられます。
対戦相手への接続先、patch可否、flag period、checker仕様は大会ルールから確認し、
明示された範囲を越えて自動化しません。

## スウォーム（独立ワーカーの並列実行）

大規模CTFでは、1つの会話で順番に解くのではなく、独立したワーカーを並列で動かします。

```sh
.venv/bin/metis swarm run CONTEST_ID --workers 8 --minutes 40          # Claude Code
.venv/bin/metis swarm run CONTEST_ID --workers 8 --agent codex          # Codex
.venv/bin/metis swarm status CONTEST_ID
.venv/bin/metis swarm stop CONTEST_ID
```

- 各ワーカーは大会キューから優先度の高い問題を1つ借り、その問題専用の新しいセッションで
  時間内（`--minutes`）に解きます。カテゴリが偏らないよう、作業中でないカテゴリを優先します。
- 1つの問題を同時に借りられるのは1ワーカーだけです。ワーカーが落ちても貸し出し期限が切れれば
  キューに戻ります。
- 公式判定で正解すれば solved、ワーカーが blocked にすればそのまま、`--max-sessions` 回やっても
  判定が出なければ blocked（理由のメモ付き）、それ以外はキューに戻ります。
- ログは `.metis-state/swarm/<contest>/` に問題ごと・ワーカーごとに残ります。
- ワーカーは無人で動くため、Claude Code の sandbox を「auto-allow」モードにし、必要な
  許可ドメインを事前に登録しておきます（確認ダイアログでは止まれません）。
- 利用枠はおおむねワーカー数に比例して消費されます。問題サーバーへの負荷も考え、大会の
  ルールが許す範囲で台数を決めてください。

### 経過の確認（ダッシュボードとtmux）

```sh
.venv/bin/metis swarm run CONTEST_ID --workers 4 --tmux     # tmuxで画面を自動分割して起動
.venv/bin/metis swarm watch CONTEST_ID                       # ダッシュボードだけを表示
.venv/bin/metis swarm watch CONTEST_ID --once                # 現在の状況を1回だけ表示
```

`--tmux` を付けると、tmuxのセッション `metis-<大会IDの先頭8文字>` を作り、次のウィンドウを並べます。

| ウィンドウ | 内容 |
| --- | --- |
| dashboard | 得点、各ワーカーが今していること、問題ごとの状態（色分け）、最近の出来事。`q` で閉じる、`s` で停止依頼 |
| workers（5台目以降は workers2） | ワーカーごとのライブログ。実行したコマンド、考えたこと、エラー、終了時の所要時間と費用 |
| swarm | スウォーム本体。終了すると Enter で閉じる |

ウィンドウの切り替えは `Ctrl-b` のあと `n`（次）または `w`（一覧）、セッションから一時的に離れるのは
`Ctrl-b` のあと `d` です。再接続は `tmux attach -t metis-<ID>` です。ワーカーごとのログは
`.metis-state/swarm/<contest>/w1.log` などにも残ります。tmuxが無い場合は `brew install tmux` で入れます。

### 引き継ぎ（handoff）

無人のワーカーはサインイン済みのブラウザを使えません。問題インスタンスの起動やログインが最後に必要な問題では、
ワーカーは解法・送る値・ソルバーを WriteUP と note に残し、状態を `handoff`（引き継ぎ待ち）にして終了します。
`handoff` の問題は再びキューに戻らず、ダッシュボードに `HO` と表示されます。

```sh
.venv/bin/metis swarm handoff CONTEST_ID            # 一覧（JSON）
.venv/bin/metis swarm handoff CONTEST_ID --prompt   # claude --chrome にそのまま渡せる作業指示
```

対話セッションでは1問ずつ、インスタンス起動 → `remote grant ... --replace` → `latest` で接続 → ブラウザで提出 →
`web attest` → `contest update` で solved → WriteUP 更新、の順に進めます。

## 大会ランチャー（./play）

```sh
./play                    # メニュー：既存の大会の続き / 新しい大会（URL を入力）
./play CONTEST_ID         # メニューを飛ばして続きから
./play --new URL --name 名前 --workers 4   # 新規登録して、ワーカー4台も同時に起動
```

選ぶと tmux セッション `metis-<IDの先頭8文字>` が開きます。

| ウィンドウ | 内容 |
| --- | --- |
| claude | 対話型の Claude Code（`--chrome` 付き）。大会の情報・ルール・最初にやること（新着の取り込み、状況報告、引き継ぎ待ちの処理）を渡して起動 |
| dashboard | `metis swarm watch` |
| swarm / workers | ワーカー台数を1以上にしたときだけ。あとから `metis swarm run ID --workers N --tmux` を実行しても同じセッションに追加される |

実行中の大会を選ぶと、その画面に戻ります。Claude Code を終了してもウィンドウは残り、`claude --continue` で再開できます。

### 大会の情報とルール

```sh
.venv/bin/metis contest new URL --name 名前      # サイト種別を判定し、既定のルールで登録
.venv/bin/metis contest info CONTEST_ID          # サイト・ルール・進捗・要対応の問題
printf '%s' '{"rules": {"ends_at": "2026-12-31 21:00 JST"}}' | .venv/bin/metis contest configure CONTEST_ID
```

ルールの項目は `submission`（api / browser）、`instance_limit`、`writeup_publish`（anytime / after_end / never）、
`starts_at`、`ends_at`、`notes` です。AlpacaHack は「ブラウザで提出・インスタンス1つ・解法公開は期間終了後」が既定です。
`./play` はこれを毎回 Claude への最初の指示に入れます。

### 新着問題の取り込み（問題が増え続ける大会）

```sh
.venv/bin/metis contest refresh CONTEST_ID                 # CTFd / rCTF は API から一覧を読む
.venv/bin/metis contest refresh CONTEST_ID --file list.json # 一覧をブラウザで読んだ結果（AlpacaHack など）
```

ボードに無い問題だけを追加します。既存の問題の状態・run・メモは変わりません（配点と解答数だけ更新）。
AlpacaHack Daily のように毎日増える大会は、`./play` で大会を選べば Claude が最初に新着を取り込みます。


## 本番大会の手順（live contest recipe）

1. runを作ります。run IDは `metis codex intake` か `metis web open` が返すものだけが使えます。
   `metis prepare` のrun IDは Codex セッションではないため、`contest update` / `plan` / `agent` は
   "Codex session not found" で失敗します。大会の問題は `competition` として分類します（既定の
   `unlisted` のままだと `memory learn` / `writeup save` の technique は保存されません）。

   ```sh
   .venv/bin/metis codex intake --title 'CHALLENGE' --artifact ./files/chal.zip --evaluation-split competition
   ```

2. 問題とrunを結び付けます。

   ```sh
   printf '%s' '{"state":"investigating","run_id":"RUN_ID"}' \
     | .venv/bin/metis contest update CONTEST_ID CHALLENGE_ID
   ```

3. 計画を立てます。`--mode auto`（既定）は単純な問題だと `sequential` を返し、wave を消費します。
   委任したいときは最初から指定します。

   ```sh
   .venv/bin/metis plan RUN_ID --mode delegated --reason 'independent static and crypto hypotheses'
   ```

注意:

- `--database` はグループ名の後、サブコマンドの前に置きます:
  `metis contest --database .metis-state/metis.sqlite dispatch CONTEST_ID`。
- `contest dispatch` は問題を `investigating`（担当者なし）にします。`swarm`（`contest claim`）は担当者なしの
  `investigating` も借りられますが、dispatch の timebox が切れると `blocked` になります。1つの大会では
  どちらか一方の運用を選ぶのが安全です。
- `contest board` の `blocked_by_prerequisites` は、前提問題が `abandoned`（断念）になり永久に解放されない
  問題だけを示します。前提が未解決で待っているだけの問題は含まれません。

stdinへ渡すJSONの例:

```sh
# contest add: 配列、または {"challenges":[...]}
printf '%s' '[{"challenge_id":"web-1","title":"Login","category":"web","points":300,"estimated_minutes":20,"confidence":0.5,"prerequisites":[]}]' \
  | .venv/bin/metis contest add CONTEST_ID

# agent report: hypothesis/evidence/falsifier/next_action は5〜2000文字、event_sequences は観測済みのrunイベント番号
printf '%s' '{"hypothesis":"Signature check skips the alg field","evidence":"Source shows verify() without algorithms list","falsifier":"A tampered token is rejected","next_action":"Replay one tampered token in the sandbox","event_sequences":[1,2],"status":"supported","artifact_refs":[]}' \
  | .venv/bin/metis agent report RUN_ID WAVE_ID ASSIGNMENT_ID

# writeup save: summary 必須。techniques は run_id が competition/practice のrunにリンクしている場合だけ保存される
printf '%s' '{"summary":"Forged the session token via the missing algorithm check.","analysis":"...","solution":"...","tags":["jwt"],"run_id":"RUN_ID","source_split":"competition","techniques":[{"title":"JWT alg confusion","category":"web","summary":"Verify that the algorithm list is pinned","conditions":"JWT session cookie"}]}' \
  | .venv/bin/metis writeup --root writeups save CONTEST_ID CHALLENGE_ID

# memory learn: 抽象的な方法のみ（flag・認証情報・長い符号化文字列は拒否される）
printf '%s' '{"title":"JWT alg confusion","category":"web","summary":"Check that the verifier pins the algorithm list.","conditions":"JWT session cookie","outcome":"success","source_run_id":"RUN_ID"}' \
  | .venv/bin/metis memory learn
```

`writeup save` は technique を保存できなかった場合も終了コード0を返しますが、出力の最上位に `warning` を付け、
stderr にも同じ内容を出します。
