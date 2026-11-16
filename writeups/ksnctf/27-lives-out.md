# Lives out

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 27 |
| カテゴリ | rev |
| 配点 | 150 |
| 状態 | 解決済み（公式判定で正解: 2026-11-12 23:57 JST） |
| Flag | `FLAG_HTcJT6pUmFEd2PH2` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | rev, pe, x64, game-of-life, static-analysis, capstone |
| 問題URL | https://ksnctf.sweetduet.info/problem/27 |
| METIS run | `8d68b12251d441b2ad314ade03ecd3c9` |

## 概要

x64 Win32 GUIの16x16ライフゲームで全セルを消灯した時に表示されるメッセージを静的解析で復元した。

## 解析

01-00-livesout.exe は PE32+(x64)のGUIアプリ。起動時に srand(time)+rand で16x16盤面(行ストライド0x12、枠付き)を乱数初期化する。WM_LBUTTONDOWN(0x201)はクリックしたセル1つの反転、WM_TIMER(0x113)は生誕3/生存2-3のコンウェイ・ライフ1世代更新、WM_PAINT(0xf)は盤面を描画し、全256セルが0のときだけ21個のUTF-16文字をスタック上の定数配列から計算してTextOutWで表示する。盤面は乱数なのでフラグは盤面に依存せず、定数のみで決まる。計算は out[n]=(((A[n]-S[n])&0xffff)^X[n])+Add[n] (16bit)で、A,S,X,Add は各21個のdword配列(rbp-0x20, rbp+0x40, rbp+0xa0, rbp+0x100)。movdqa/mov即値で初期化される定数を.rdataから取り出して計算した。

## 解法

capstoneで.textを逆アセンブルし、0x140001567以降の定数コピーを自前で再現(27-livesout-flag.pyに保存)。4配列を復元して式を適用すると文字列が得られる。実行はせず静的解析のみ。実際に盤面を全消灯する必要はなく(ライフゲームの全消灯探索は不要)、定数から直接導出できる。

## 使用したスクリプト

- [27-disasm.py](files/27/27-disasm.py)
- [27-livesout-flag.py](files/27/27-livesout-flag.py)

## 学び・再利用できる手法

ゲーム/パズル系バイナリは、勝利条件の先にある出力生成ルーチンが入力(乱数盤面)非依存であれば、パズルを解かず定数から直接導出できる。movdqaの即値コピーはcapstoneのdetailでrip相対アドレスを解決すると自動抽出しやすい。

- **勝利条件後の出力生成ルーチンを静的に再現**（rev）: パズル解答に依存しない定数配列からの文字列生成処理を逆アセンブルで特定し、Pythonで同じ演算を再現して出力を得る。
  - 適用条件: 出力生成が入力や乱数に依存せず定数のみで決まる場合
- **rip相対のSSE定数コピーをcapstoneで自動抽出**（rev）: movdqaのrip相対ロードとスタック保存を追跡し、スタック上に構築される定数配列をファイルから復元する。
  - 適用条件: x64バイナリで定数がmovdqa経由でスタックへコピーされる場合

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
| 00-problem.html | 8,633 | `d1ac84cf6c7c1723f3318a1ed7555f54e250691d6b91e5589485d10d4fd6e6cf` |
| 01-00-livesout.exe | 10,752 | `a22b5611723256c523e265776b9b00da9823a285b32f8dc1f455dad629adbde2` |

<sub>METIS writeup — 更新: 2026-11-13 17:45 JST</sub>
