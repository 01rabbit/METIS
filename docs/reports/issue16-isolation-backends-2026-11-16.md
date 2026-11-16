# Issue #16 Codex の隔離: spawn ツールの調査、子プロセスの禁止、Linux 版（2026-11-16）

## spawn ツールは設定で無効化できるか

codex-cli 0.166.0 で、次の 4 通りを実 Codex で試した。どの場合も `collaboration.spawn_agent` などはモデルに提示されたままで、
spawn の試みは（`--ephemeral` のため）失敗し、カナリアに検知された。

- 既定（`--disable multi_agent` など、ドライバの既定のフラグ）
- `-c collaboration_mode="none"`
- `-c agents.max_concurrent_threads_per_session=1`
- `--enable multi_agent_v2` と上記のスレッド上限の組み合わせ

バイナリ内の設定キーにも、collaboration ツールを外す項目は見つからなかった。この版では、設定で無効化する方法は無いと判断する。

## OS レベルでの対策

### macOS（Seatbelt）

- 既存のファイル隔離・ネットワーク隔離に加え、`(deny process-fork)` と `(deny process-exec)` を入れた。
  例外は、そのターンの Codex バイナリの実行だけ。shell、補助プロセス、setuid プログラムはどれも起動できない。
- 実 Codex で検証した。CLI 側の防御をすべて外した状態（shell 有効、Codex 自身の sandbox は `danger-full-access`、
  `--ephemeral` と `--disable` を削除）で、shell コマンド 4 件と sub-agent 経由のコマンドを指示した。すべて
  `code-mode host failed to spawn: Operation not permitted` で実行されなかった。sentinel は漏れず、書き込みも起きなかった。
- `codex-probe` のセルフテストに `child_process_denied` を加えた。全項目が合格している。

### Linux（bubblewrap、新規）

- `--unshare-all`（user・pid・net・ipc・uts・cgroup の各名前空間）、`--die-with-parent`、`--new-session`、`--cap-drop ALL`、
  `--clearenv` で起動する。マウントするのはシステムのディレクトリ（読み取り専用）、Codex パッケージ（読み取り専用）、
  ターン専用ディレクトリだけで、ホームディレクトリと共有の一時ディレクトリはそもそも見えない。
- 外部への通信は、新しいネットワーク名前空間の中から、127.0.0.1:18080 → 転送器 → Unix ソケット → ホスト側の許可リスト付き
  プロキシ、という経路だけに限る。直接の通信は経路が無い。
- bubblewrap は no-new-privileges を設定するので、setuid による権限昇格は効かない。
- 子プロセスは禁止できない（seccomp フィルタは未導入）。ただし子プロセスも同じ名前空間・capability 0・no-new-privileges の下にいる。
- 起動前に `bwrap` が実際に名前空間を作れるかを確かめる。作れない場合は隔離なしとみなし、起動を拒否する（fail closed）。

検証:

- Docker の Linux コンテナ（python:3.13-slim + bubblewrap、aarch64）で、セルフテストと偽 Codex の脱出試験が合格した。
  確認した項目は、保護領域の読み取り・一覧・書き込みの拒否、直接通信の失敗、許可リスト外の宛先の拒否と記録、NoNewPrivs=1。
- Docker Desktop 上では、非特権ユーザーの bubblewrap はネットワーク名前空間のループバックを設定できなかった。
  そのためコンテナの root に `SYS_ADMIN` と `NET_ADMIN` を付けて実行した（中のプロセスは capability 0 になる）。
  非特権ユーザーでの動作は、下記の CI で確認した。
- CI（GitHub Actions の ubuntu-latest、**一般ユーザー**）では bubblewrap が使え、Linux の 2 件を含む 9 件が合格した
  （run 43869904885）。非特権ユーザーでの動作はこれで確認できた。名前空間を作れない環境では、この 2 件は skip になる。
- 最初の CI では、setup-python のインタプリタ（`/opt/hostedtoolcache`）がサンドボックス内に無く、転送器が起動しなかった。
  実行中のインタプリタのインストール先を読み取り専用でマウントするよう直した。
- **Linux 上の実 Codex は試していない。** 手元にあるのは macOS 版の Codex だけで、Linux のコンテナに認証情報を持ち込む試験は行っていない。

## OS ごとの保証範囲

| 項目 | macOS（Seatbelt） | Linux（bubblewrap） |
| --- | --- | --- |
| ホームと共有の一時ディレクトリの読み書き | 拒否（プロファイル） | 見えない（マウントしない） |
| 外部への通信 | プロキシの許可リストのみ | 名前空間の中からプロキシ経由のみ |
| 子プロセス | 禁止（fork・exec） | 可能。ただし同じ名前空間・capability 0・NoNewPrivs |
| 権限昇格 | exec を Codex 本体に限る | NoNewPrivs、capability 0 |
| 実 Codex での確認 | 実施済み | 未実施（偽 Codex のみ） |
| 隔離を用意できない場合 | 起動を拒否する | 起動を拒否する |

## 未解決

- spawn ツールそのものをモデルから隠すこと（この CLI の版では不可能）。
- Linux での子プロセスの禁止（seccomp フィルタ）と、実 Codex での確認。
- Windows は未実装（起動を拒否する）。


## 追加調査（2026-11-16）

Linux の Codex 実行側に seccomp を追加し、fork/vfork とプロセスを作る clone を拒否する。
clone3 は ENOSYS で拒否し、必要なスレッド用 clone は許可する。これは exec や Codex 内部の
サブエージェントを禁止しない。x86-64 と aarch64 のみを対象とし、他のアーキテクチャでは起動に失敗する。
Linux aarch64 コンテナの単独フィルタ試験ではスレッド作成成功と fork 拒否を確認した。
コンテナの既定制限下では bubblewrap の名前空間作成が失敗したため、統合試験は未確認。
Linux 上の実 Codex と非特権環境の新フィルタは未確認である。

ローカルの Codex CLI 0.169.0 の `features list` は `multi_agent` を deprecated、
`multi_agent_v2` を stable と表示する。フラグの存在や値だけではツールの非提示は証明されない。
上記の実機観測を超える、spawn を確実に無効化するサポート済み設定は確認できていない。
新たな認証情報のコピーや実モデル呼び出しは行っていない。

Windows は調査のみ。Windows の sandbox はこの実装から使用しておらず、Job Object、
AppContainer やネットワーク制御の組み合わせについて設計・実証していない。
Windows では従来どおり fail closed であり、同等の隔離保証は主張できない。
