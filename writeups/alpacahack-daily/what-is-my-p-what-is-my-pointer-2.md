# what is my pointer 2

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | what-is-my-pointer-2 |
| カテゴリ | pwn |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:08 JST） |
| Flag | `Alpaca{33333333nnnnnnnnvvvvvvvv11111111rrrrrrrr00000000nnnnnnnn}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | pwn, libc, environ |
| 問題URL | https://alpacahack.com/daily/challenges/what-is-my-pointer-2 |
| METIS run | `e72d3d9b71b846b6b664e01154583620` |

## 概要

任意アドレス読みループ＋printfリーク。libc base算出後 environ を読み envp を辿って FLAG 環境変数を取得。

## 解析

printf@ リーク -> libc_base=leak-0x60100。environ=base+0x20ad58。*environ=envp。各 envp[i] の文字列先頭を見て 'FLAG='。libcはpin留めubuntu:24.04(amd64)イメージから抽出。

## 解法

environ 経由で FLAG= 文字列を読み出し（バイナリはホスト未実行、遠隔サービスへの読みのみ）。

## 使用したスクリプト

- [wimp2-solver.py](files/what-is-my-p/wimp2-solver.py)

## 学び・再利用できる手法

任意アドレス読みループ＋printfリーク。libc base算出後 environ を読み envp を辿って FLAG 環境変数を取得。

- **printf leak -> libc base -> environ for stack secrets**（pwn）: An arbitrary-read primitive plus a leaked libc function pointer lets you compute the libc base (leak - symbol_offset), then read the libc `environ` global (base + environ_offset) to obtain the stack address of the envp array, walk it, and read any environment string (e.g. a flag passed via an env var). Offsets come from the exact target libc, which for a pinned Docker base can be extracted from that image.
  - 適用条件: A loop/arbitrary read where you supply an address and get its contents, a leaked libc pointer, and a secret stored in the environment or elsewhere reachable from a libc global.

## METISの記録

- 期間: 2026-11-13 20:31 JST 〜 2026-11-13 21:08 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, remote_service_solver_pipe ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:08 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,639 | `9af545a52d7677b23064c403a404c8150bbebe6a4ca88797f48d96baf6e0fe9e` |
| 01-00-what-is-my-pointer-2.tar.gz | 3,825 | `fae09c673bf735f92a1491754597782c259a59ffb4a48b500d1a709e73516edb` |
| .metis-web/fa0287c609ef4ac8a93675c596b4c3b3.gz | 3,825 | `fae09c673bf735f92a1491754597782c259a59ffb4a48b500d1a709e73516edb` |
| .metis-remote/5ed7a682d94f469fa7948c120ea236be.recv | 1,012 | `14433d441d9d0b5bea0473a5c97289b6fbc3659791a56b4bc861fdb24eb26495` |

### 接続先

- 34.170.146.252:5941

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
