# what is my pointer 3

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack B-SIDE |
| 問題番号 | what-is-my-pointer-3 |
| カテゴリ | pwn |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-21 12:46 JST） |
| Flag | `⟦answer:alpacahack-b-side/what-is-my-pointer-3.md#flag⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | pwn, malloc, mmap, libc-leak, arbitrary-read, glibc, gnu-hash, __progname_full |
| 問題URL | https://alpacahack.com/daily-bside/challenges/what-is-my-pointer-3 |
| METIS run | `c185517cc92042e9b98ea7bb57734cd6` |

## 概要

AlpacaHack B-SIDE の pwn 問題『what is my pointer 3』(Topic: malloc, Very Hard)。メニューは (1) malloc(size) の返り値を %p で表示、(2) 任意アドレスの 8 バイトを表示（任意アドレス read）。main 冒頭で program_invocation_name = getenv("FLAG") とされており、libc のデータシンボル __progname_full が FLAG 文字列（スタックの環境変数領域）を指す。large malloc の mmap 隣接を使って libc ベースを漏洩し、任意 read だけで libc の ELF/GNU ハッシュをメモリ解析して __progname_full のアドレスを解決、その値（フラグへのポインタ）を辿って文字列を回収した。ローカル libc を一切使わないバージョン非依存の解法。

## 解析

バイナリは PIE/NX/Full RELRO・カナリアなし（ただし書き込みプリミティブは無く read 専用なので関係しない）。配布物に libc.so.6 は無く、Dockerfile は ubuntu:24.04 ピン留め（glibc 2.39）。ギフトコメント `*ELF("libc.so.6").sym["__progname_full"] == getenv("FLAG")` が示す通り、__progname_full（= program_invocation_name）に FLAG 文字列のポインタが入る。鍵は 2 つ: (a) 任意 read からどうやって libc ベースを得るか、(b) ローカル libc なしで __progname_full のオフセットをどう解決するか。(a) は 128KiB を超える malloc が mmap チャンクになり、Linux の mmap は top-down 配置のため libc マッピングの直下に置かれる性質を利用。返り値ポインタから上方向に ELF マジック 0x464c457f を走査して libc ベースを特定（確保領域はゼロ埋めなので、領域末尾の直後からページ単位で探索）。(b) は得た libc ベースから ELF ヘッダ→PT_DYNAMIC→DT_SYMTAB/DT_STRTAB/DT_GNU_HASH を任意 read で辿り、GNU ハッシュ（h=5381, h=h*33+c）で __progname_full のシンボルを引いて st_value を取得（在メモリの .dynamic エントリはローダが絶対アドレスへ再配置済み）。&__progname_full の値がフラグへのポインタ（スタック 0x7ffe... 帯）で、そこから 8 バイトずつ NUL まで読んでフラグを得る。

## 解法

1) 接続後メニューを読み飛ばし、(1)allocate に size=0x100000 を与え、[DEBUG] iteam=<P> を取得。2) cand=P+0x100ff0 から上方向にページ単位で (2)print pointer を使い 8 バイト読みし、下位 4 バイトが 0x464c457f になるアドレスを libc_base とする。3) libc_base から e_phoff(+0x20)/e_phnum(+0x38) を読み、PT_DYNAMIC(p_type==2) の p_vaddr を取得して .dynamic を走査、DT_SYMTAB(6)/DT_STRTAB(5)/DT_GNU_HASH(0x6ffffef5) の絶対アドレスを得る。4) GNU ハッシュで "__progname_full" を検索し symtab エントリの st_value から &__progname_full = libc_base + st_value を算出。5) そのアドレスの値 fp（= getenv FLAG ポインタ）を読み、fp から 8 バイトずつ読んで NUL までを連結しフラグを復元。read は全て (2) の scanf(%p)→printf(%lx) プリミティブ経由。リモットとの往復が多いため、over-read を保持する自前バッファで recv を高速化した。

## 使用したスクリプト

- [wimp3-exploit.py](files/what-is-my-p/wimp3-exploit.py)

## 学び・再利用できる手法

ローカル libc が手元に無くても、任意 read さえあれば在メモリの ELF/GNU ハッシュを解析して任意のシンボルアドレスを解決でき、libc バージョン非依存の解法になる。large malloc の mmap 隣接は『heap→libc』の定番リーク手段。__progname_full/program_invocation_name は getenv の返り値をそのまま保持するため、1 回の read でスタック上の値へ辿れる。

- **large-malloc mmap 隣接による libc リーク**（pwn）: mmap 閾値（既定 128KiB）超の malloc は mmap チャンクとなり、top-down 配置で libc マッピング直下に置かれる。返り値ポインタから上方向に ELF マジックを走査して libc ベースを得る。
  - 適用条件: 確保サイズを攻撃者が指定でき、確保ポインタ（またはその近傍）が漏洩し、任意アドレス read がある場合。
- **在メモリ ELF+GNU ハッシュ解析による libc 非依存シンボル解決**（pwn）: 任意 read だけで libc の ELF ヘッダ→PT_DYNAMIC→DT_SYMTAB/STRTAB/GNU_HASH を辿り、GNU ハッシュでシンボルを検索して絶対アドレスを求める。ローカル libc 不要・バージョン非依存。
  - 適用条件: libc ベースが判明し、任意アドレス read が利用でき、ローカルに正確な libc が無い場合。
- **__progname_full からの環境変数値リーク**（pwn）: program_invocation_name(=__progname_full) に保持された文字列ポインタを 1 read で取得し、その先の文字列を読む。本問は getenv("FLAG") がそこに代入されていた。
  - 適用条件: 対象が program_invocation_name/__progname_full に機密文字列ポインタを格納し、任意 read がある場合。

## METISの記録

- 期間: 2026-11-21 12:24 JST 〜 2026-11-21 12:46 JST
- 使用アクション数: 17（official_flag_submission_browser ×1, read_only_artifact_analysis ×13, remote_service_solver_pipe ×3）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-21 12:46 JST | correct | 1 |

### 仮説の変遷

| 時刻 | 状態 | 仮説 | 根拠 |
| --- | --- | --- | --- |
| 2026-11-21 12:37 JST | supported | Arbitrary read + malloc mmap adjacency leaks libc then __progname_full | Large malloc above mmap_threshold returns mmap chunk placed directly below libc; scan up to ELF magic for libc base; parse PT_DYNAMIC + GNU hash in remote memory to resolve &__progname_full; its stored char* is the getenv(FLAG) pointer; read the string via the 8-byte read primitive |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 361,834 | `9bbd610356eac6205bc20dbd0f2b7c650448802f73a0cc6c7bb80ece45d06be1` |
| 01-00-what-is-my-pointer-3.tar.gz | 4,266 | `e103867bd7d2a71ad218c514a2d4ed851a25309a50f25e3cfc68f19661ad6c6a` |
| .metis-derived/12fa47268b74450e9537c7b535f0f432.bin | 30,720 | `4d0678f99fa558a0461745db02e6f471079ccf3e9ebb638bda8fbffe76c36f59` |
| .metis-derived/436be7b1010d4e7487a7893dc021840e.bin | 1,016 | `2869abf0413381a6eae09ceedef6dd6b96f9551aeb002998a2f0551f87d17c59` |
| .metis-derived/6eda15e756e349a599086566ab0687c3.bin | 969 | `0767d4492dd49a26cd664046418a0517a2598768b045204fcb8ac05b28f55170` |
| .metis-derived/df32b409075a4a5397db1987d0359474.bin | 96 | `802bbff3b15d90d96a23f2569321be9174e433f4507d80b588d0b9c15024c87e` |
| .metis-derived/7baf75289765470f9cde2375b87b8f1c.bin | 16,560 | `5c16fe0598176eb67e41c95ea83bf217ddba522c9f58e353f9befb3562173685` |
| .metis-remote/e73765b19ff246ec9559a60359903409.recv | 4,222 | `0c08dce16122c51180e494d73c588fcce2f15f92b2c5c2cc12f1e9356b94be8a` |
| .metis-remote/f0bdbe4d2e82410b8a1bbb281d6b7d70.recv | 2,542 | `08bfca2d890ea185319e9bb4fb4be8b7a3b713a829b67a868cc3296d7bde263c` |

### 接続先

- 34.170.146.252:34985

<sub>METIS writeup — 更新: 2026-11-21 12:47 JST</sub>
