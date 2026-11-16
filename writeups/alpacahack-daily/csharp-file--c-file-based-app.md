# C# File-based app

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | csharp-file-based-app |
| カテゴリ | rev |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 20:39 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/csharp-file--c-file-based-app.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, dotnet, brotli |
| 問題URL | https://alpacahack.com/daily/challenges/csharp-file-based-app |
| METIS run | `7a8fbd6e1602495286c09775108ceb15` |

## 概要

正解入力は chal.cs 中の base64 を Brotli 展開した値。デコードするだけ。

## 解析

IsCorrect() は base64 定数を Base64->BrotliDecoder で展開し入力UTF-8と比較。

## 解法

base64decode -> Brotli decompress（Node zlib.brotliDecompressSync）。

## 使用したスクリプト

- [csharp-solve.js](files/csharp-file-/csharp-solve.js)

## 学び・再利用できる手法

正解入力は chal.cs 中の base64 を Brotli 展開した値。デコードするだけ。

- **Recover expected input from an embedded base64+Brotli blob**（rev）: A checker that compares your input to decompress(base64decode(const)) is inverted by decoding that constant directly (base64 then Brotli), no execution needed.
  - 適用条件: A comparison checker whose target is a compressed constant in the source/binary.

## METISの記録

- 期間: 2026-11-13 20:30 JST 〜 2026-11-13 20:39 JST
- 使用アクション数: 2（official_flag_submission_browser ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 20:39 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,600 | `c476dc5646c6633a50b3288ca4325ea08e14bc72474f75f64724518b8d3eabeb` |
| 01-00-csharp-file-based-app.tar.gz | 988 | `2d1e8efc872ee02374f24f6e8f12969ef9f3739c6148b006606a167ced1dde81` |
| .metis-web/aa5fbd3d82094c2385dcd6da5351160d.gz | 988 | `2d1e8efc872ee02374f24f6e8f12969ef9f3739c6148b006606a167ced1dde81` |

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
