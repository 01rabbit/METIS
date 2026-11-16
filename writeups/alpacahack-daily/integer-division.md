# integer division

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | integer-division |
| カテゴリ | misc |
| 配点 | 3 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:30 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/integer-division.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, integer-overflow, SIGFPE |
| 問題URL | https://alpacahack.com/daily/challenges/integer-division |
| METIS run | `e4e3faf690e84d6a9261c4604842029c` |

## 概要

INT_MIN / -1 は x86-64 の idiv で #DE となり SIGFPE。y==0 のチェックだけでは防げない。

## 解析

chal.c は y==0 のみ弾き x / y を計算する。server.py は chal の終了コードが非0なら FLAG を表示する。

## 解法

x=-2147483648, y=-1 を送る。INT_MIN/-1 は結果が int に収まらず idiv が #DE を起こし、Linux が SIGFPE にして returncode != 0 になる。

```python
sys.stdout.write('-2147483648\n-1\n')
```
`metis remote pipe` で送信。

## 使用したスクリプト

- [idiv-solver.py](files/integer-divi/idiv-solver.py)

## 学び・再利用できる手法

整数除算の例外は0除算だけでなく INT_MIN / -1 でも起きる。

- **INT_MIN divided by -1 trap**（misc）: 符号付き最小値を -1 で割ると idiv が #DE を起こしプロセスが SIGFPE で落ちる
  - 適用条件: 0除算だけを検査する C プログラム

## METISの記録

- 期間: 2026-11-13 21:53 JST 〜 2026-11-13 22:30 JST
- 使用アクション数: 5（official_flag_submission_browser ×1, read_only_artifact_analysis ×3, remote_service_solver_pipe ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:30 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,809 | `703dca42c7f9d95298b339907679084d387f2a02d33f859e02265aced0c2a39b` |
| 01-00-integer-division.tar.gz | 3,584 | `3cdd470dc4691504d69cd5910dfdec0489c02b6a51a8bda3410dd4236fc12ec3` |
| .metis-remote/f73ae69ec70149f1bd4ebcad0e93410d.recv | 113 | `d01f9c896e25d7933c3dfc4a208e9958a583deab818ae3fa674bd5b455a5f9fa` |

### 接続先

- 34.170.146.252:57224

<sub>METIS writeup — 更新: 2026-11-13 22:30 JST</sub>
