# what is my pointer 4

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | what-is-my-pointer-4 |
| カテゴリ | pwn |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:05 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/what-is-my-p-what-is-my-pointer-4.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | pwn, oob, aslr |
| 問題URL | https://alpacahack.com/daily/challenges/what-is-my-pointer-4 |
| METIS run | `1d9c064f0a1f49a9921f3fcb18d91c2a` |

## 概要

getenv(FLAG) のアドレスをリーク。malloc(-1)=NULL -> item[index] が絶対アドレス読みになり、複数接続で env 上のフラグを再構成。

## 解析

size=-1 で malloc 失敗 NULL。item[index]=*(index*8)。index=flag_addr//8+K で各ワードを読む。接続毎にリークとoff=addr%8から位置を決めて再構成。

## 解法

K=0.. を別接続で読み (位置->バイト) を集約。

## 使用したスクリプト

- [wimp4-solver.py](files/what-is-my-p/wimp4-solver.py)

## 学び・再利用できる手法

getenv(FLAG) のアドレスをリーク。malloc(-1)=NULL -> item[index] が絶対アドレス読みになり、複数接続で env 上のフラグを再構成。

- **malloc(huge)->NULL then OOB index for absolute read**（pwn）: When malloc(size) fails it returns NULL; a subsequent arr[index] then dereferences index*sizeof(elem) as an absolute address. Combined with a leaked target address, pick index=target//8 to read an arbitrary 8-byte-aligned word. If only one read per connection is allowed, reconnect and reassemble the secret across connections using each connection's fresh leak and known alignment.
  - 適用条件: User-controlled allocation size that can force NULL, an unchecked signed index into the returned pointer, and a leaked absolute address of the secret.

## METISの記録

- 期間: 2026-11-13 20:32 JST 〜 2026-11-13 21:05 JST
- 使用アクション数: 13（official_flag_submission_browser ×1, remote_service_solver_pipe ×11, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:05 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 374,575 | `421a394fee36ad0cba87b5efdc58712fc75f6b63a174d8207f982e3372f2083c` |
| 01-00-what-is-my-pointer-4.tar.gz | 4,139 | `8f97670a80ee5c1947f6712137ccaefce0f624e6c0bb70344b704414916d32cc` |
| .metis-web/89149058336b4f83b28151ec10acd426.gz | 4,139 | `8f97670a80ee5c1947f6712137ccaefce0f624e6c0bb70344b704414916d32cc` |
| .metis-remote/54471bffff4045b9ac79f729489a7e55.recv | 92 | `8be99941d221a0bbb6ad61e72e170667f6ef79c0627eeea989a7994a27b7d79c` |
| .metis-remote/f65d00e6b756491297407bdcd186f243.recv | 92 | `86be78cce6da8a71702c3d5066422c03ac315d292f90637b9769765b72a3a8bb` |
| .metis-remote/a9a80fc5fe9d4fbbab0deb63d19bb920.recv | 92 | `dbf204420832f64fc4d0e4a95a341de506d93dfac7f5b7270e461c1b125f8083` |
| .metis-remote/90da382f6a4149489197c2b6c8358dd5.recv | 92 | `318ed4618f4468a19e29c927b2f58940ed4cce77db10e5658519b5a2e3d9af86` |
| .metis-remote/781a75fcee3a4550888b5f71e7044e3b.recv | 92 | `06f3238d20fc4eb5fcad6604154e0843f85d95cd91bdc375b3f59b97c1de9bec` |
| .metis-remote/0a232af420ac477a8be63c5755c92202.recv | 92 | `637b0b37338e9c4af8ff6c777580e5a72675951ea62c9022e790c146b05768e9` |
| .metis-remote/7427307e625e420f95c02929ae3280dc.recv | 92 | `676aad4984b5df20702b6666e7964ef0105ddfe261c95aaa9406780e03ca2f16` |
| .metis-remote/7bea271ba205491e8e03db22c8637bfb.recv | 92 | `5f619bca9d9be58cf9b0b0c6d7dbecd129ffa591a1292ff2c8d17b74ba0b8db7` |
| .metis-remote/f0a7a6fe2ff6442bba53754c788f43f0.recv | 92 | `8af5e90fa578b813eb474440ab00a184eeb22ba6553f198b54d5b97e3d68a9f3` |
| .metis-remote/b07f62361c8f4ad1af86f9aa8293094e.recv | 90 | `8caed006c7ed8f98c33569ebea867e973df74312e9affd503adba4406b729bba` |
| .metis-remote/442d754c3bdb4a7782402c7bd1d9d467.recv | 77 | `ebb6827d1cc975f196e7b6f47a1ed6178272ef30cbb5ac01047975dfa52656ac` |

### 接続先

- 34.170.146.252:5633

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
