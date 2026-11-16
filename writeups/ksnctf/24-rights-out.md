# Rights out

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 24 |
| カテゴリ | misc |
| 配点 | 100 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:57 JST） |
| Flag | `FLAG_EhiAfPAAY7JG3UZ2` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | ksnctf, rev, dotnet, lights-out, xor |
| 問題URL | https://ksnctf.sweetduet.info/problem/24 |
| METIS run | `b77b787e5a624dcfa1d3d556d2499303` |

## 概要

.NET製の5x5ライツアウト。最後の8クリック列と全消灯の一致で解錠され、その列をXOR鍵として埋め込み暗号文を復号したものがフラグ。

## 解析

rightsout.exe は .NET(Windows Forms)。ILを自作ディスアセンブラで読んだ。button_Click は押したボタン番号idxで update(idx)(十字トグル)し、履歴配列(8要素)を左シフトして末尾にidxを入れる。check は全消灯(Array.IndexOf(state,true)<0)かつ履歴==静的8整数配列のとき、33整数配列を 履歴配列[i%8] とXORして文字列化しMessageBoxで表示する。パズルを解くだけでは不十分で、最後の8手が決まった列でなければならない。静的データは .text 内 0x538(鍵) と 0x558(暗号文)。

## 解法

```python
key = struct.unpack("<8I", d[0x538:0x538+32])   # (1,7,16,11,14,19,20,18)
c   = struct.unpack("<33I", d[0x558:0x558+132])
print("".join(chr(c[i]^key[i%8]) for i in range(33)))
# The flag is FLAG_EhiAfPAAY7JG3UZ2
```
実行は不要(静的に復号)。フラグ: `FLAG_EhiAfPAAY7JG3UZ2`

## 使用したスクリプト

- [24-il.py](files/24/24-il.py)
- [24-decode.py](files/24/24-decode.py)

## 学び・再利用できる手法

.NETはILが素直に読める。鍵が実行時状態(クリック履歴)から導かれる場合でも、比較対象の静的配列そのものが鍵になる。FieldRVAのデータ位置は鍵候補/暗号文候補を総当たりして既知接頭辞("The flag"/"FLAG")で確定できる。

- **.NET IL静的解析で比較対象配列を鍵として復号**（rev）: ILを逆アセンブルして check ロジックを特定し、同一アセンブリ内の静的配列をXOR鍵・暗号文として取り出し、既知接頭辞で位置合わせして復号する。
  - 適用条件: .NET実行ファイルで鍵・暗号文が静的配列として埋め込まれている。

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
| 00-problem.html | 8,645 | `3483cfc091edcfb142f9b2a581ff3ebdcf0e601c03280d2ecfaa3e49e73b9623` |
| 01-00-rightsout.exe | 15,360 | `5ea9611264ca4acc28fb6cd73d736363b2784909ce8a9ac5c99840a566d3dda3` |

<sub>METIS writeup — 更新: 2026-11-13 16:08 JST</sub>
