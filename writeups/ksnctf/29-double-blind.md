# Double Blind

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 29 |
| カテゴリ | forensics |
| 配点 | 50 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:37 JST） |
| Flag | `FLAG_NTSCFTTKP5ZDDW` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | forensics, docx, metadata, ooxml |
| 問題URL | https://ksnctf.sweetduet.info/problem/29 |
| METIS run | `e7ce25727a8448fe9fe7ade48fc6d282` |

## 概要

docx内の画像altテキスト(docPr descr)に残った作成環境のパスから、ユーザー名に混入した余分な文字xを除去してフラグを得た。

## 解析

対象docxはZIPの中央ディレクトリとdocPropsが欠落しており標準のzipfileでは開けなかったため、ローカルファイルヘッダを直接パースして各パートを展開した。本文は著者名が空(No Author Given)で、コメントや変更履歴、隠し文字は無かった。画像のdocPr descrに、フォルダ名remove_xを含むWindowsパスがあり、そのユーザー名がFLxAG_NTSCFTTKP5ZDDWだった。

## 解法

descr内のユーザー名からxを取り除く(remove_xのヒント)とフラグ形式になる。

## 使用したスクリプト

- [29-inspect.py](files/29/29-inspect.py)
- [29-writeup.py](files/29/29-writeup.py)

## 学び・再利用できる手法

メタデータが削られていても、本文XML内の画像descrや属性に作成環境のパスが残ることがある。壊れたZIPはローカルヘッダから手動で復元できる。

- **中央ディレクトリ欠落ZIPの手動展開**（forensics）: ローカルファイルヘッダを順に読みdeflateを展開する
  - 適用条件: EOCDが無くunzipが失敗するOOXML
- **OOXML内の画像descr属性の確認**（forensics）: document.xmlのdocPr descrに残る作成環境パスを調べる
  - 適用条件: docPropsが削除された文書

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:37 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:37 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,757 | `3bc0931da099f246467c849e3292e5daef8d801863175f7285a4c948ffed560a` |

<sub>METIS writeup — 更新: 2026-11-13 18:10 JST</sub>
