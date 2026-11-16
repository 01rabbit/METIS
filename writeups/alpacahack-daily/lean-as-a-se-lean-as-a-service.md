# Lean as a Service

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | lean-as-a-service |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:58 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/lean-as-a-se-lean-as-a-service.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, lean, rce |
| 問題URL | https://alpacahack.com/daily/challenges/lean-as-a-service |
| METIS run | `1a6c64d148b647838063d0a9797ad657` |

## 概要

Lean の #eval が elaboration 時に IO を実行する。readDir で /flag-*.txt を特定し readFile。

## 解析

app.py は lean Main.lean の stdout/stderr を返す。#eval (do ... : IO Unit) で任意IO。IO.Process.run はタイムアウトしたので readDir/readFile 版を使用。

## 解法

#eval でルート列挙 -> flag-<md5>.txt を readFile して出力。

## 使用したスクリプト

- [lean-exploit.lean](files/lean-as-a-se/lean-exploit.lean)

## 学び・再利用できる手法

Lean の #eval が elaboration 時に IO を実行する。readDir で /flag-*.txt を特定し readFile。

- **Code execution via Lean #eval at elaboration time**（misc）: `lean Main.lean` runs #eval terms during elaboration and prints their output. An `#eval (do ... : IO Unit)` can perform arbitrary IO (IO.FS.readDir/readFile, IO.Process.run) to read a flag file; output is returned by any service that echoes compiler stdout.
  - 適用条件: A service that compiles/checks attacker-supplied Lean source and returns stdout/stderr.

## METISの記録

- 期間: 2026-11-13 20:32 JST 〜 2026-11-13 20:58 JST
- 使用アクション数: 10（official_flag_submission_browser ×1, scoped_web_requests ×9）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:58 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 378,459 | `c676b81a7ec366790ddbf79c8fa0934c1d96821673a42473e06360398834ba5f` |
| 01-00-lean-as-a-service.tar.gz | 2,264 | `81037a89404350f8dcc47e995240921bc84840e46dc9c172f86bce8d8b77891c` |
| .metis-web/523adcda6c464e71a92e6fce6f53bb89.gz | 2,264 | `81037a89404350f8dcc47e995240921bc84840e46dc9c172f86bce8d8b77891c` |
| .metis-web/5ff85de267dd461482b604be85aea5fe.bin | 1,911 | `09c7e22dd48399a2683757f0065db41d91bd57bbf4a195ed54342db1fee66aae` |
| .metis-web/3faec93a179c4fae8aa0d330b4a7a34a.bin | 1,802 | `2d721c2bed840ddce778db51f6b33aa9e22265a36f2348467efd22fd3d8f7c8e` |
| .metis-web/6a286b4af9bb429fb9a8132e6709b252.bin | 1,958 | `14dac0f88cc55a7fd58d64bdb9a93ed5617c8061bd76a36b404a0b7ef8a08f61` |
| .metis-web/2b0b2717fe6f424d97728bf35fb3103b.bin | 1,835 | `e4f1ce8d01d4781f9b12c4b843f33859629e32331171a9f468607d54577f5e82` |
| .metis-web/3f651698cad34f7aaa09c6fb065ebdc8.bin | 1,849 | `895d1305da351f5e33a6b8f60f00a05c089495aafdf69f352d74d2724ac8b966` |
| .metis-web/1864053489a54a5f9f8d2c789545660a.bin | 2,175 | `89dffc5d318dec6b4568c266572a9e93afc40a0fde22ee33466bfcb0ad6da109` |
| .metis-web/9903eeedce6c4c06b7958cf0f1434de5.bin | 2,108 | `6cab3394ba7f9516491f8ed710f334fc5d14ee3bcf7590901bd6a0f69b16412f` |
| .metis-web/fd61ff9394f84e2d90667a1a7195a98f.bin | 1,877 | `65fccb1555c17f505c7014da829e0bb94e319666d57dc05056e68faa6d4f6433` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
