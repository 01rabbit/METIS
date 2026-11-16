# Deep Flag Network

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 40 |
| カテゴリ | misc |
| 配点 | 100 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 00:40 JST） |
| Flag | `FLAG_un5A5BUMF8JwjYi` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | ctf-misc, ml, model-inversion, qr-code, reed-solomon, affine |
| 問題URL | https://ksnctf.sweetduet.info/problem/40 |
| METIS run | `b93a96488adf423d8832c81ae2d7b6fa` |

## 概要

Deep Flag Network (問題40): モデルは活性化関数なしの全結合+BNのためアフィン写像。完全な重みでpublished確率を再現し、QR構造制約下でflagクラスの確率を最大化して25x25のQRを復元、RS誤り訂正で復号した。

## 解析

Dense/BN(推論)/Softmaxのみで非線形がないため logits = A x + c (x=1024画素)。variables.dataの連続float配置を探索しno_flag_0.pngの公開確率と一致する配置を確認。flag.pngはQRコード(v2, 25x25, 1px/module, 白=1)を32x32に配置したものと推定。入力を箱制約で単純に勾配上昇させると雑音だらけで復号できないため、finder/timing/alignment/dark moduleを固定し、残りのモジュールをlog p(flag)の貪欲ビット反転で最適化(オフセット(3,3)でp=0.995、複数seedで同一解)。

## 解法

1) 40-deep-flag-recover.pyの重み復元 2) 40-qr-search.pyでQR構造制約付き探索(格子を40-qr-grid.jsonに保存) 3) 40-qr-decode.pyでformat情報(mask7, EC Q, 距離0)を読み、Reed-Solomon(BM+Forney)で5シンボル誤りを訂正しバイトモード復号。

## 使用したスクリプト

- [40-deep-flag-recover.py](files/40/40-deep-flag-recover.py)
- [40-qr-search.py](files/40/40-qr-search.py)
- [40-qr-decode.py](files/40/40-qr-decode.py)

## 学び・再利用できる手法

活性化のないネットワークは線形写像なので逆問題を解析的に扱える。出力を最大化する入力は雑音を含むため、既知の構造(QR機能パターン)を制約にし、誤り訂正符号で最終補正する。

- **活性化なしNNのモデル反転**（misc）: 線形層とBNのみのネットワークをアフィン写像として扱い、目的クラス確率を最大化する入力を求める
  - 適用条件: 重みが入手可能で非線形活性化がない
- **構造制約付きビット探索とRS訂正によるQR復元**（misc）: QRの機能パターンを固定し、モデルの対数確率を貪欲反転で最適化、残る誤りをReed-Solomonで訂正
  - 適用条件: 復元対象がQRコードと推定でき、サイズ・位置を総当たりできる

## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 00:40 JST
- 使用アクション数: 1（official_flag_submission ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 00:40 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 9,693 | `b1d848b789b1df2a55dde30287019994c0df4d96b2bc2e8202a38340b54a384e` |
| 01-00-q40.zip | 7,765,715 | `cbb4eb433bd305c800537eff44668be5b2948a47643fb3b78efa0e0b14c5f1a1` |
| 02-01-train.py | 1,809 | `e375bb3e1e38d3c3e1397020983b5e9801de84dc6b578cd1b96fde6a5355a5c0` |
| 03-02-flag_ai.py | 579 | `6412849002909ec57fcfecf1c0afdd1e41491bd1f1e522563cef25a22c91cf2d` |
| 04-03-no_flag_0.png | 897 | `a030bc8bb8e6cc796e9b56ec93c09af13bb69b9c8169ad53f89d2192c14fac38` |

<sub>METIS writeup — 更新: 2026-11-13 18:12 JST</sub>
