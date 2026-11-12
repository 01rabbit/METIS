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
