# CodexでCTFを解くためのクイックスタート

## 1. 取得と準備

現在の実装は `metis-full-implementation` ブランチにあります。

```sh
git clone --branch metis-full-implementation https://github.com/01rabbit/METIS.git
cd METIS
python3 scripts/setup.py
./metis-codex
```

Codexが準備状態を確認し、問題URLまたはローカル配布ファイル、必要に応じて
プラットフォームやchallenge IDを日本語で確認します。標準的な利用では別の
モデルAPIキーもDockerも不要です。

起動コマンドはDaybreakとマルチエージェント機能を有効にします。Daybreakが
全体を管理し、独立した解析だけを利用可能な下位モデルへ通常2〜4担当で並列化
します。単純作業には小さいモデルと必要最小限の文脈を使い、重複調査や目的の
ない大量起動を避けます。公式解答の送信と判定はDaybreakが一元管理します。

## 2. 問題を取得

標準的なCTFdの問題は次の形です。

```sh
.venv/bin/metis web open 'https://ctf.example/challenges' --adapter ctfd --challenge-id 12
```

一般的なHTML問題ページでは次の形です。

```sh
.venv/bin/metis web open 'https://ctf.example/problem/12' --adapter html
```

同一オリジンの一般的な配布ファイルは自動取得されます。別の配布用オリジンは、
大会が明示したものだけを `--allow-origin` で追加します。ログインが必要な場合、
トークンやCookieは `metis web auth` のマスク入力か既存の環境変数を使います。
値を会話やコマンド引数へ貼り付けません。

## 3. 解答と自己修正

Codexはファイル形式を確認し、制限付きの解析ツールで根拠を集めます。抽出した
文字列はまだ正解ではありません。候補は公式CTFd API、または結果条件を明示設定
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
