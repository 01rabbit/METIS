# METISを別の場所・別のMacへ移す

METISのデータはすべてこのフォルダの中にあります。フォルダごと移してセットアップを1回
実行すれば、移す前と同じように動きます。

## 何がどこにあるか

| 場所 | 内容 | git |
| --- | --- | --- |
| `src/` `tests/` `docs/` `sandbox/` `integrations/` ほか | METIS本体 | 管理対象 |
| `writeups/` | 大会ごとのWriteUP、一覧、手法ナレッジ（flagを含む） | 管理対象 |
| `.metis-state/` | run・判定履歴・仮説・技術カード・大会キュー・配布ファイル・解析スクリプト・認証情報 | 対象外 |
| `.claude/` | Claude Code用のskill・エージェント・コマンド | 管理対象 |
| `.claude/settings.local.json` | このMac専用の設定（sandboxの許可ドメインと除外コマンド） | 対象外 |
| `.venv/` `.metis-bootstrap/` `.metis-cache/` | Python環境とキャッシュ（移動後に自動で作り直す） | 対象外 |

フォルダの外にあるのは、作り直せるものだけです。

- OrbStack／Docker内のサンドボックスイメージ
- uvが入れたPython本体

## 移し方

### 同じMacの別の場所へ

```sh
mv ~/personal/METIS ~/work/METIS   # 隠しフォルダ（.metis-state など）ごと移す
cd ~/work/METIS
python3 scripts/setup.py --all
```

### 別のMacへ

`.metis-state/` には実行記録と認証情報が入っているため、gitでは移りません。
フォルダ全体を、隠しファイルを含めてコピーしてください。

```sh
# 元のMacで（隠しファイルも含めて1つのファイルにまとめる）
cd ~/personal && tar czf METIS-backup.tgz --exclude=METIS/.venv --exclude=METIS/.metis-cache METIS

# 新しいMacで（展開してセットアップ）
tar xzf METIS-backup.tgz && cd METIS
python3 scripts/setup.py --all
```

新しいMacでは、事前にOrbStack（またはDocker Desktop、Colima、Podman）を起動しておきます。
`--all` を付けると、サンドボックスイメージもそのMac向けに作り直します。

## `python3 scripts/setup.py --all` がすること

1. `.venv` が別の場所で作られたものなら削除し、この場所で作り直します。
2. `.metis-state` 内の古い絶対パスを、移動しても使える相対パスに書き換えます。
3. `integrations/claude-code` を `.claude/` にコピーします。`.claude/settings.local.json` の
   除外コマンドの絶対パスを今の場所に合わせ、許可ドメインはそのまま残します。
4. コンテナエンジンにサンドボックスイメージが無ければ作ります。エンジンが止まっている場合は
   スキップし、その旨を表示します。
5. `metis doctor` で準備状態を表示します。

何度実行しても問題ありません。`./start` も、`.venv` が別の場所で作られたものだと検出すると、
自動でセットアップを実行します。

## 移した後の確認

```sh
.venv/bin/metis doctor             # "ready": true、sandbox の image_present が true
.venv/bin/metis codex board        # 以前のrunが一覧に出る
.venv/bin/metis contest board CONTEST_ID
```

Claude Codeのsandboxを使う場合は、新しいMacでも許可ドメイン（例:
`ksnctf.sweetduet.info`）が `.claude/settings.local.json` に入っていることを確認してください。
`tar` で移した場合はそのまま入っています。
