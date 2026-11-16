# Alpha Mixed Cipher

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 30 |
| カテゴリ | rev |
| 配点 | 80 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:00 JST） |
| Flag | `FLAG_2HPvt34yakC6o8ru` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, shellcode, alpha2, alphanumeric, x86, capstone, static-analysis |
| 問題URL | https://ksnctf.sweetduet.info/problem/30 |
| METIS run | `bb1e67a54d5c4f8e9b4a0c57a6164779` |

## 概要

英数字のみのx86シェルコード(Alpha2系mixedcaseエンコード)をデコードし、MessageBoxに渡される文字列を静的に復元した。

## 解析

問題文の長い英数字列は SkyLined ALPHA2 の mixedcase デコーダ。先頭の VTX630... はSEH(fs:[0])を使ったGetPCスタブ、IIII...は ecx 調整、jAXP0A0AkAAQ2AB2BB0BBABXP8ABuJI がデコードループ。ループは xor [ecx+0x30],al(al=0x41) で imul の即値 0x51 を 0x10 に自己書換えした後、out=((c1*0x10)&0xff)^c2 を2文字ごとに1バイトとして先頭(文字列index 107, 'J'の位置)から in-place でデコードする。デコード結果(276バイト)は典型的なWindowsシェルコード(PEBからkernel32を辿りROR13ハッシュでAPI解決、LoadLibraryA('user32.dll')、MessageBoxA)で、文字列はpush即値で組み立てられ、[esp+0x15]を0でNUL終端している。

## 解法

30-alpha-decode.py で文字列をデコードし(実行せず)capstoneで逆アセンブル。push 0x47414c46,0x5048325f,0x34337476,0x436b6179,0x72386f36,0x20205875 のリトルエンディアン連結の先頭21バイトがMessageBoxのテキスト=フラグ。ハマりどころ: HTMLの正規表現が途中のmetaタグで切れて文字列が短くなる点と、imul即値が自己書換えされる点。

## 使用したスクリプト

- [30-alpha-decode.py](files/30/30-alpha-decode.py)

## 学び・再利用できる手法

自己書換えを含むデコーダは、パッチされる位置(ecx+0x30が指す命令バイト)を確認する。0x51->0x10の書換えを見落とすと出力がゴミになる。ASCII列を総当りで乗数・開始位置を振り、可読文字列(hll Ah32.dhuser等)が出るかで検証するのも有効。

- **英数字限定シェルコードのデコーダを自前再実装**（rev）: 自己書換えを含むALPHA2系デコードループをPythonで再現し、実行せずに平文シェルコードを得て逆アセンブルする。
  - 適用条件: 英数字のみのx86ペイロードでデコードループが特定できる場合
- **パラメータ総当りと可読文字列で復号検証**（rev）: 開始位置や乗数を総当りし、出力中に文字列やAPI名が現れるかで正しいデコード方式を判定する。
  - 適用条件: デコーダの細部が曖昧で、平文に文字列が含まれる場合

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:00 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:00 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 9,475 | `05275f0125df114e7b8eb1bdb5b97501acd10bbdea169fbe88ae91da2213b26f` |

<sub>METIS writeup — 更新: 2026-11-13 17:45 JST</sub>
