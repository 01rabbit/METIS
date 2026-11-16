# QUIZ ALPACASHOCK

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | quiz-alpacashock |
| カテゴリ | misc |
| 配点 | 1.5 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:46 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/quiz-alpacas-quiz-alpacashock.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, quiz, counting |
| 問題URL | https://alpacahack.com/daily/challenges/quiz-alpacashock |
| METIS run | `03652905224544bb93b18bd1033d2c6f` |

## 概要

Daily AlpacaHack の A-SIDE 問題が開始から何問目かを数えて ⟦answer:writeups/alpacahack-daily/quiz-alpacas-quiz-alpacashock.md#2⟧ 形式で答えるクイズ。9/1 公開分は 258 問目。

## 解析

問題文のヒントどおり、公開日(2026-09-01)までに公開された A-SIDE 問題数をカレンダーから数える。Daily のカレンダーは `https://alpacahack.com/daily?month=YYYY-MM` で月を切り替えられるため、各月のページを取得して問題セルを集計した。複数日にまたがるセル(例: 6-8日 Bitflip RSA)は 1 問として数え、前後月のはみ出し表示は重複して数えないようにした。開始は 2025-12-01 の「AlpacaHack 2100」(1問目)。

## 解法

- 2025-12〜2026-07 は毎日 1 問: 31+31+28+31+30+31+30+31 = 243
- 2026-08: 1 / 2 / 3-4 / 5 / 6-8 / 9-10 / 11-12 / 13-15 / 16-17 / 18-20 / 21-23 / 24-26 / 27-28 / 29-31 の 14 問
- 2026-09-01 の QUIZ ALPACASHOCK 自身 = 1

合計 243 + 14 + 1 = 258 → `⟦answer:writeups/alpacahack-daily/quiz-alpacas-quiz-alpacashock.md#1⟧`。ブラウザのフラグ欄から提出し Solved を確認。

## 学び・再利用できる手法

カレンダー形式の一覧は月パラメータで過去分を取得できる。複数日にまたがるセルと月境界の重複表示に注意して数える。

- **Count items across paginated calendar views**（misc）: When a question asks for a cumulative count over a calendar-style listing, fetch each period via the site's own query parameter, de-duplicate multi-day cells and boundary padding from adjacent months, and sum per period.
  - 適用条件: A quiz-style challenge whose answer is derivable from public listing pages and the listing supports period selection.

## METISの記録

- 期間: 2026-11-13 21:43 JST 〜 2026-11-13 21:46 JST
- 使用アクション数: 21（official_flag_submission_browser ×1, scoped_web_requests ×20）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:46 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 368,770 | `9c2741775db6ff1c7746723616c4d45cc83b1bb325a71b735ca656264d95825b` |
| .metis-web/4c6218edcdba499c8067f3cfdcca82c4.bin | 305,924 | `05014ceba32a7fc5a763887b827c183f1280c4adafaa6ca410e1a99b639eac47` |
| .metis-web/17569ccaf1aa4660b86b072af787f171.bin | 319,273 | `6c6ecb12ff113d3069409262e2d5763e5e8b3b20fd98266076dbaf31d59b076f` |
| .metis-web/dbed66a0d5624d9ca822a3e58384da82.bin | 328,334 | `191c35250f5ca2a624a5b8652d795725b3ded5553a78826111b2258c64c78f4b` |
| .metis-web/6552871f17ce45fe983a7e1b4041988c.bin | 326,501 | `0c14b72143b500fcf58ec40176bb916f678e0358aa2d8998da364f7e549e0cd2` |
| .metis-web/2d75f570281149f9a0fcf4ab767fc1cb.bin | 327,438 | `04aa468fd7181ed51358aa3791732357667b692f6cfa79255c6082f1374f43d3` |
| .metis-web/b2bd66c4a2ab481a83e589dd9f04f102.bin | 339,842 | `b5be51e1c91181a6642b94b65a17b05a85910523f293f0e2f04a4669dcee3bb2` |
| .metis-web/5e76163999a8411fad72093ecc5677cf.bin | 326,180 | `dbff1791e0ac9067bc194eaef3c68977eb812947661bb9433c68ae7f8f2041be` |
| .metis-web/9ff8b909545e426c921b3e9c5f951e56.bin | 330,359 | `49af7ac63e02ed10e356007aa828bdfb42fd8ec00018b37b28178b76020404ee` |
| .metis-web/4086921b7de242929c3992e767bea62c.bin | 324,905 | `ec91ff9b2b19cbb48f7d748565d96595b8b6bb931439091a9d3cce9bc225dfb7` |
| .metis-web/7bba9732173e49718ee9f272bd46f881.bin | 327,607 | `867ce0b342cdb2c601922f2e2dd25e88a335cf1d0349d90bdf7dd598b8c58c49` |

<sub>METIS writeup — 更新: 2026-11-13 21:46 JST</sub>
