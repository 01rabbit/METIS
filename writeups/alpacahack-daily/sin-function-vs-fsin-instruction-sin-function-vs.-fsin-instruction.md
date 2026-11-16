# sin function vs. fsin instruction

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | sin-function-vs-fsin-instruction |
| カテゴリ | rev |
| 配点 | 4 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 22:32 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/sin-function-vs-fsin-instruction-sin-function-vs.-fsin-instruction.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, x87, fsin |
| 問題URL | https://alpacahack.com/daily/challenges/sin-function-vs-fsin-instruction |
| METIS run | `c3abbfa249804db4acf3a03611064d05` |

## 概要

x87 fsin は |x| >= 2^63 でオペランドを変更せず返す。theta=1e300 を入力すると libm の sin と fsin の差が 1337 を超える。

## 解析

chal.c は fabs(sin(theta) - fsin(theta)) > 1337 のとき FLAG を出力する。libm の sin は [-1,1] だが、fsin は範囲外(|x|>=2^63)で C2 フラグを立て st(0) を変更しない。inf/nan は弾かれるが 1e300 は通る。

## 解法

theta に 1e300 を送る。sine_1 は約 -0.82、sine_2 は 1e+300 となり FLAG が出力される。

```python
sys.stdout.write('1e300\n')
```
`metis remote pipe` で送信。

## 使用したスクリプト

- [sin-solver.py](files/sin-function/sin-solver.py)

## 学び・再利用できる手法

命令の仕様(範囲外オペランドの扱い)を確認する。ライブラリ関数と命令の結果は入力が大きいと乖離する。

- **x87 fsin out-of-range operand passthrough**（rev）: fsin は |x|>=2^63 の引数を変更せず返すため、大きな有限値で libm の sin と大きく乖離する
  - 適用条件: fsin と sin の結果を比較するプログラムが大きな有限 double を受け付ける

## METISの記録

- 期間: 2026-11-13 21:50 JST 〜 2026-11-13 22:32 JST
- 使用アクション数: 11（official_flag_submission_browser ×1, read_only_artifact_analysis ×7, remote_service_exchange ×1, remote_service_solver_pipe ×2）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 22:32 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 376,955 | `359da1751a8beeab2ddc93fd26fac3600eb9025e0cc63f8f8b26ad59a0eb9d8b` |
| 01-00-sin-function-vs-fsin-instruction.tar. | 4,225 | `05e789cfc03788bf447deedd32bddfb62420d756fd4a55433d5926a4f71175d9` |
| .metis-derived/aa7d8ef857b8456ebf63d04e3fd1879e.bin | 30,720 | `5646bcde34f6c5e652c174145dbde3d331775626136d3eae3d5ad469d5415b34` |
| .metis-derived/4525e9a52abf483f9e5a7d25e5490fa8.bin | 320 | `7c98a0db7dda34c4137ae4d9fecf7967dd7e2e147024cb604931f9ad9a5aa116` |
| .metis-derived/f7aeb74b834c48cd8bd9fd70e6ac227d.bin | 1,445 | `f4bff33759e3ff02374296947506f10e4428f0aad9a0d3d37e12f30dfc2aa048` |
| .metis-remote/9d9d0c867c6a49689c232bd4835651c8.recv | 98 | `c8b0d34e1f55f4fa447bfa49d26cc20892d73b3a26c113955c0d3892e7e25cf4` |

### 接続先

- 34.170.146.252:57819
- 34.170.146.252:42433

<sub>METIS writeup — 更新: 2026-11-13 22:32 JST</sub>
