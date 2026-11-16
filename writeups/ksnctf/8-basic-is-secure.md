# Basic is secure?

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 8 |
| カテゴリ | misc |
| 配点 | 50 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:58 JST） |
| Flag | `⟦answer:writeups/ksnctf/8-basic-is-secure.md#1⟧` |
| タグ | forensics, pcap, http-basic, base64 |
| 問題URL | https://ksnctf.sweetduet.info/problem/8 |
| METIS run | `2cea088de8bc44c89e45b715de595464` |

## 概要

pcap 内の HTTP Basic 認証の Authorization ヘッダを base64 デコードするとパスワードがフラグ。

## 解析

q8.pcap には /~q8/ への GET が 2 回あり、1 回目は 401 (WWW-Authenticate: Basic realm="Secret")、2 回目に Authorization: Basic cTg6⟦answer:writeups/ksnctf/8-basic-is-secure.md#enc3⟧0dB が付き 200 が返る。Basic 認証は base64 のみで暗号化されていない。

## 解法

```
strings q8.pcap | grep Authorization
```
```python
import base64
print(base64.b64decode('cTg6⟦answer:writeups/ksnctf/8-basic-is-secure.md#enc3⟧0dB').decode())
# q8:⟦answer:writeups/ksnctf/8-basic-is-secure.md#1⟧
```
user=q8, password=フラグ。

## 使用したスクリプト

- [8-solve.py](files/8/8-solve.py)

## 学び・再利用できる手法

Basic 認証は平文同然。pcap では認証ヘッダをまず grep する。

- **pcap から HTTP Basic 資格情報を抽出**（forensics）: strings/grep で Authorization ヘッダを見つけ base64 デコード
  - 適用条件: 暗号化されていない HTTP の通信キャプチャがある

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-12 23:58 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-12 23:58 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,556 | `563788042a9876bdeb860929bfb194002bdd42408c13aa32180aacd62370aecd` |
| 01-00-q8.pcap | 5,064 | `197af9df81ec45236aa83edef6a33f478e950cb86d539eba4adb6bd26a7b7ae6` |

<sub>METIS writeup — 更新: 2026-11-13 15:57 JST</sub>
