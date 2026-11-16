# Auxiliary vectors are our friends

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | auxiliary-vectors-are-our-friends |
| カテゴリ | pwn |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:11 JST） |
| Flag | `Alpaca{Auxiliary_vectors_are_a_gift_from_the_Linux_kernel}` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | pwn, canary, auxv, ret2win |
| 問題URL | https://alpacahack.com/daily/challenges/auxiliary-vectors-are-our-friends |
| METIS run | `d07bf640a3d54b41b96364517efb914d` |

## 概要

getauxval(AT_RANDOM=25) のアドレスを読める -> glibc カナリアの素(AT_RANDOM先頭8B, byte0=0)が漏洩。BOF -> ret2win。

## 解析

main が getauxval(type) の指す16Bを表示。AT_RANDOM を指定しカナリア=bytes[0:8] の byte0 を 0 に。win=0x40135f。read(0,buf,32)。

## 解法

type=25 でリーク -> payload: A*8 + canary + B*8 + p64(0x40135f)。

## 使用したスクリプト

- [aux-solver.py](files/auxiliary-ve/aux-solver.py)

## 学び・再利用できる手法

getauxval(AT_RANDOM=25) のアドレスを読める -> glibc カナリアの素(AT_RANDOM先頭8B, byte0=0)が漏洩。BOF -> ret2win。

- **Leak AT_RANDOM via getauxval to recover the stack canary**（pwn）: glibc derives __stack_chk_guard from the 8 bytes at the AT_RANDOM auxiliary vector (with the least-significant byte forced to 0x00). If the program exposes getauxval(type) and lets you read memory at the returned pointer, query AT_RANDOM (25), read its 16 bytes, and the canary is bytes[0:8] with byte0 zeroed. Then overflow past the known canary to ret2win.
  - 適用条件: A primitive that returns getauxval(user_type) and reads memory at that address, plus a canaried stack overflow and a win gadget.

## METISの記録

- 期間: 2026-11-13 20:32 JST 〜 2026-11-13 21:11 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, remote_service_solver_pipe ×1, scoped_web_requests ×3）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:11 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,429 | `4f324f7aa3d6e8aa39fcc7677e2155ea569cfa5e108484a3e31b8d78eb8c4961` |
| 01-00-auxiliary-vectors-are-our-friends.tar | 4,543 | `0b1573a84cf1cb2ed8a50914404364fd058a2128a2670207b731c8ac3373324c` |
| .metis-web/4dace881752f4d3ab11df165e75ff329.gz | 4,543 | `0b1573a84cf1cb2ed8a50914404364fd058a2128a2670207b731c8ac3373324c` |
| .metis-web/3b6bfe20dc054a73b9596efdcdf99560.gz | 4,543 | `0b1573a84cf1cb2ed8a50914404364fd058a2128a2670207b731c8ac3373324c` |
| .metis-web/c84054d82fb94586bff079410f676ef1.gz | 4,543 | `0b1573a84cf1cb2ed8a50914404364fd058a2128a2670207b731c8ac3373324c` |
| .metis-remote/0ba07e3f0c9246aeb37400f7ee644366.recv | 166 | `f0afdda93ceac1b596d22e75e19e1e5c791b8b0af3185e1a56eb7e1d2f13ef08` |

### 接続先

- 34.170.146.252:33252

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
