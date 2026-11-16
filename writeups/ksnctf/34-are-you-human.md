# Are you human?

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 34 |
| カテゴリ | web |
| 配点 | 220 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 15:18 JST） |
| Flag | `FLAG_4nanCgVEFnZZysxW` |
| タグ | web, forensics, ocr, reed-solomon, gf256, captcha, jpeg, kmeans |
| 問題URL | https://ksnctf.sweetduet.info/problem/34 |
| METIS run | `a95c1aa32255482496d2e4854c55d11c` |

## 概要

ksnctf #34 Are you human?。CAPTCHA風PNG 7571枚をOCRして得たhex列を Reed-Solomon(255,64) で誤り訂正し JPEG を復元、その赤文字を幾何的に読み取ってフラグを得る。

## 解析

ecc.py は64バイトごとに191バイトのパリティを付け、全体の約1%をランダムに破壊する。GF(256)は原始多項式0x11dだが要素はバイト値を指数として扱う（255がゼロ元）点が罠。符号語は [パリティ191 | データ64]（データ全体の後に全パリティが連結）。訂正能力が95シンボルと非常に大きいため、OCRはクラスタリング＋目視ラベルの粗い精度で十分（平均6.5誤り/ブロック）。画像の赤文字は回転・手書き風で大小文字の判定が難しく、補間した回転画像では誤読した（4回の不正解）。生の赤画素の点群を座標回転して高さを数値で比較して確定。

## 解法

## 手順
1. `image.zip` を展開すると `image/%08x.png`（1024x32、7571枚）。1枚＝16バイト＝hex 32文字で、背景色1色と文字色4色のみ（アンチエイリアスなし）。ノイズ線は文字と同系色の1px線。
2. セルを32x32に切り、色ごとに最頻の非背景色を文字色として2値化（`34-extract.py`）。
3. 2x2 opening で1px線を除去し bbox を切り出して 14x22 に正規化（文字高は22-26pxでほぼ一定）。k-means(k=48)でクラスタ化し、モンタージュを目視して各クラスタに16進文字を割当（先頭タイル `FFD8FFE1 0018 4578 6966 0000 4949 2A00` = JPEG/Exif ヘッダで検証）（`34-norm.py`, `34-cluster2.py`）。
4. `ecc.py` の GF は「バイト値＝α の指数（255=0）」という対数表現。符号語 c(x) の c[0..190]=パリティ、c[191..254]=データ。根は α^0..α^190。これで Berlekamp-Massey + Chien + Forney（b=0）を実装（`34-decode.py`）。
```python
val=lambda b: 0 if b==255 else A[b]      # byte -> field element
cw[:191]=map(val,parity); cw[191:]=map(val,data)
S=[pev(cw,A[i]) for i in range(191)]     # syndromes
```
   OCR誤りは1ブロック平均6.5個（最大15、訂正限界95）、失敗ブロック0。結果は有効な 320x240 の baseline JPEG（`34-flag.jpg`）。
5. JPEG 内の赤い斜め手書き風文字を読む。赤画素(r>190,g<110,b<110)の点群を PCA の主軸角(約36度)で**座標回転**（リサンプリングなし）し、点描画で拡大（`34-redtext.py`）。
6. グリフ別に回転後の高さを計測: 大文字 F,L,A,G,4,C,V,E,F,Z,Z,W は約20-21、小文字 n,a,n,n,s,x は約13-16（a は 15.9）。y,g は下降部で約19。よって `n`(4の直後) は h ではなく n、`a` は小文字、`ZZ` は2つとも大文字。

## フラグ
`FLAG_4nanCgVEFnZZysxW`

## 使用したスクリプト

- [34-extract.py](files/34/34-extract.py)
- [34-norm.py](files/34/34-norm.py)
- [34-cluster2.py](files/34/34-cluster2.py)
- [34-decode.py](files/34/34-decode.py)
- [34-redtext.py](files/34/34-redtext.py)

## 学び・再利用できる手法

OCRの大文字小文字の誤読対策: 補間した回転画像ではなく、生の赤画素点群を座標回転し、グリフごとの高さを数値比較する（大文字約20、小文字約13-16）。見た目が似た文字(n/h, a/A, Z/z)は目視ではなく幾何量(高さ・幅・ascender有無)で判定する。RSの訂正能力が十分大きい場合、OCRは完璧でなくてよい。クラスタ→ラベルの粗い対応で足りる。ecc.py の独自GF実装は表現(対数/値)を読み違えない。先頭タイルのJPEGヘッダで対応表を検証する。提出前に候補長が FLAG_ + 16文字のテンプレートと一致するか確認する。

- **2色ノイズ付きCAPTCHAタイルのクラスタリングOCR**（forensics）: 背景色1色・文字色数色・細いノイズ線のタイルを、最頻色で2値化→2x2 openingで線除去→bbox正規化→k-meansして、モンタージュを目視でラベル付けする。
  - 適用条件: フォントが固定で文字高がほぼ一定、ノイズ線が文字より細い
- **独自GF(256)実装のReed-Solomon復号**（crypto）: ソースの要素表現（バイト=指数）と符号語の並び（パリティが低次）、生成多項式の根(α^0..α^190)を読み取り、シンドローム→BM→Chien→Forneyで復号し残余シンドロームで検証する。
  - 適用条件: 符号パラメータと多項式表現が配布ソースから読める。誤り数が訂正限界以内
- **生の画素点群の幾何的読み取りによる大文字小文字判定**（forensics）: 特定色の画素を抽出し、PCA主軸で座標を回転（リサンプリングなし）、x方向の隙間でグリフ分割して高さを数値比較する。
  - 適用条件: 回転・手書き風の文字で補間画像だと大小が曖昧

## METISの記録

- 期間: 2026-11-13 02:06 JST 〜 2026-11-13 15:18 JST
- 使用アクション数: 124（official_flag_submission ×5, read_only_artifact_analysis ×113, scoped_web_requests ×6）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 02:06 JST | incorrect | 1 |
| 2026-11-13 14:59 JST | incorrect | 1 |
| 2026-11-13 15:03 JST | incorrect | 1 |
| 2026-11-13 15:06 JST | incorrect | 1 |
| 2026-11-13 15:18 JST | correct | 1 |

### 仮説の変遷

| 時刻 | 状態 | 仮説 | 根拠 |
| --- | --- | --- | --- |
| 2026-11-13 14:59 JST | revised | Prior incorrect guess is superseded: image.zip is a zip of 7572 tiny CAPTCHA-style PNG tiles encoding T=D+E per ecc.py RS(255,64) over GF(256), not a directly readable file. | Reconstructed image.zip via chunked HTTP Range requests; OCR'd all tiles with Pillow template matching; ported ecc.py GF(256)/RS(255,64) and ran syndrome decoding on all 475 codewords with zero failed blocks (errors per block well under the correction bound); recovered a valid baseline JPEG whose overlay text gives a new candidate. |
| 2026-11-13 15:03 JST | revised | First automated OCR candidate was incorrect. Manual high-resolution re-inspection of the recovered flag.jpg overlay text (color LANCZOS crops, no binarization) shows two transcription errors versus the auto-OCR output: the character right after the leading digit has a tall ascender plus lower arch (distinct from the confirmed short-hump shape of 'n' seen later in the same string), and the doubled final-looking letter pair is actually one lowercase glyph followed by one distinctly larger/blockier uppercase glyph, not two identical uppercase glyphs. | Side-by-side crop comparison: the unambiguous 'n' later in the string (between F and the next glyph) is a small low hump with no ascender; the disputed early character is visibly taller with an ascender, inconsistent with 'n' and consistent with 'h'. Separately, the two zigzag glyphs near the string's end differ noticeably in size/weight (small vs large), consistent with lowercase-then-uppercase rather than a repeated identical character. |
| 2026-11-13 15:06 JST | revised | Both prior candidates were incorrect because the overlay text was read from an interpolated, rotated raster crop, which distorted relative glyph heights. Re-derived the text from the raw isolated red-pixel point cloud (geometric rotation of coordinates, not image resampling) and rendered it perfectly horizontal with background fully removed. | In the clean point-cloud rendering, one letter that earlier looked lowercase is clearly the same height as the surrounding capital letters (confirmed by direct visual alignment with unambiguous capitals), and a letter pair near the string's end are confirmed to be the same height as each other and as nearby capitals, contradicting the previous lower/upper mixed read for both of those positions. |
| 2026-11-13 15:18 JST | revised | Synthesizing all re-OCR passes: Daybreak independently re-rendered the final segment from the raw point cloud (no color/antialiasing artifacts) and confirmed the two zigzag-shaped letters there are identical in size/weight to each other, settling that earlier disagreement. Combined with the separately-confirmed facts that the letter right after the leading digit is the short two-hump shape (matches other confirmed instances of the same lowercase letter elsewhere in the string, not the taller ascender shape), and that the letter between two lowercase instances of that same short letter is clearly taller/bolder matching nearby capitals, a new, previously untried combination of these independently-verified facts is now assembled. | Independent point-cloud crop of the string's final segment (generated fresh, not reused from any prior pass) shows two adjacent zigzag glyphs with matching height and stroke weight, both matching the capital-letter height band established by neighboring unambiguous capitals in the same crop. |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,631 | `522caad174075b8c3ee50011289d07eb199c1113f169077ead8d2d10071d76d0` |
| .metis-web/76066713c02c4a2c9e8de61aa2f5eab0.py | 2,857 | `69259ebe5976b0b08153de2841cd192d6538542a7baf620a15597f5a90466f2c` |
| .metis-web/d0fe97ffd17e4d2b9c636b60aa0830fd.zip | 1,024 | `8906bdb735a0a9c89a92dc49ede571a748817e90b65e171e926bcab578917100` |
| .metis-web/cf22d704a6d64a898bec55be16177c94.zip | 8,371,868 | `d55b6095a94b0362e6ec387d7649a6391f9352732767633c98e78918546574d7` |
| .metis-web/da4527851fdb40e8a924130a91796c3c.zip | 8,371,861 | `91fdb2a495373fff9c75752a763c819e4f001cc35169e448d7f15d5302bbf326` |
| .metis-web/7446b2b2e50d4ccaa790693e4cf725d9.zip | 8,371,860 | `39c6a23df480097c3ade1c3852e29ff7aa79388f68a5bd0fb39ae14a899f5636` |
| .metis-web/845f676c70a04096982e6fed27d52f96.zip | 8,387,584 | `7ad91b583563445479acc7a8f2d1ca4f8d2e4c6a29425810217f87e11118b388` |
| .metis-web/fa414d5601214b489c87c2f4dab075e0.zip | 1,263,286 | `cfc21a53a7c7b5e1505f783876f40118a2828db77d0f2e9ea299424c009f4882` |
| .metis-web/039e3bed17cf4eee850f0833261bc1e2.zip | 8,387,584 | `1dc43a8243cd6cf4594de60303f5bf6fd483328f55cbf7434301652929974216` |
| .metis-web/e8d17e8988bf4f2e837b5fa64c8d0db4.zip | 8,387,584 | `58fc0f6447709f58cd1a0152ddc736813a86bc2231924be2cd8faf3d22fe8ce1` |
| .metis-web/7816cda5c2af42d98708be172c9ff2cf.zip | 8,387,584 | `2278abcec047fcb5c04dbdb6e8d186f49aca6e00e6a7f65904373f92c317f819` |

<sub>METIS writeup — 更新: 2026-11-13 15:57 JST</sub>
