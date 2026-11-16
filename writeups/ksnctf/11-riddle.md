# Riddle

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 11 |
| カテゴリ | misc |
| 配点 | 200 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:57 JST） |
| Flag | `⟦answer:writeups/ksnctf/11-riddle.md#1⟧` |
| タグ | rev, rc4, pe, mfc, static-analysis |
| 問題URL | https://ksnctf.sweetduet.info/problem/11 |
| METIS run | `5c1a9b751be34b48a1d81c5736e5446d` |

## 概要

Riddle.exe(MFC, x86)は3問のクイズに答えると最後にフラグを尋ねる。回答はRC4暗号文として.dataに保存されており、鍵が.rdataに平文であるため静的解析のみで復元できた。

## 解析

文字列からクイズ文(42, Greenland, Human)と鍵らしき文字列 M6eMYngDGFbYE9HQ を確認。ボタンハンドラ(0x401980)は入力をRC4(0x4017d0: KSAで0x403818の16バイト鍵を使用、PRGA後にXOR)で変換し、40バイト構造体{質問ptr, 暗号文[32], 長さ@+0x24}(0x405178から)の暗号文と比較する。4番目のエントリがフラグ。

## 解法

1. PE解析: .text VA 0x1000/raw 0x400, .rdata 0x3000/0x2000, .data 0x5000/raw 0x3a00。capstoneで.textを逆アセンブルしRC4(256回のS初期化, key[i&15])を特定。
2. 構造体配列(VA 0x405178, 40バイト刻み)から暗号文と長さを取り出し、鍵でRC4復号する。

```python
def rc4(k,b):
    S=list(range(256));j=0
    for i in range(256):
        j=(j+S[i]+k[i%len(k)])&255;S[i],S[j]=S[j],S[i]
    i=j=0;o=bytearray()
    for c in b:
        i=(i+1)&255;j=(j+S[i])&255;S[i],S[j]=S[j],S[i];o.append(c^S[(S[i]+S[j])&255])
    return bytes(o)
```
結果: Human / Greenland / 42 / フラグ。

## 使用したスクリプト

- [11-dis.py](files/11/11-dis.py)
- [11-solve.py](files/11/11-solve.py)

## 学び・再利用できる手法

期待値(回答)を暗号化して比較するクイズ型バイナリは、鍵と暗号文が同梱されるため実行せず静的に復号できる。RC4はKSA/PRGAの定型ループで識別できる。

- **埋め込みRC4鍵と暗号文の静的復号**（rev）: x86 PEを逆アセンブルしRC4ループを特定、鍵と比較用暗号文をデータ領域から抽出して復号する。
  - 適用条件: 鍵と暗号文が同一バイナリ内にあり、比較用構造体の配置が読み取れる

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:57 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:57 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,538 | `6ff4e70d5f52c40f68201729314b7521c6e26e00ca5802dca8b35eef511403c7` |
| 01-00-Riddle.exe | 138,752 | `17dae39da738669c6cd3c9ec50469f1d3a292915f17ea1dbf48db08c8d25af7a` |

<sub>METIS writeup — 更新: 2026-11-13 15:56 JST</sub>
