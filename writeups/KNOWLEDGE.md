# 手法ナレッジ（MUNIN）

76 件の手法カード。METISは新しい問題の取得時にこのカードを検索し、似た問題の手法を提示します（`metis memory search`）。

## crypto

### Tiled Reed-Solomon CAPTCHA payload reassembly（成功） — [出典](ksnctf/34-are-you-human.md)

A payload can be split into fixed-size blocks, each protected with a systematic Reed-Solomon code (RS(255,64) over GF(256)), and then disguised by rendering every small raw byte chunk as a tiny distorted CAPTCHA-style tile image rather than shipping raw bytes. Recovering the payload requires: fetching all tiles (chunked HTTP Range requests when a single distribution file exceeds a tool's per-request size cap), OCR'ing each tile back to bytes, then running standard RS syndrome decoding per 255-byte codeword to correct the sparse injected noise and recover the exact original data, even though per-tile OCR itself is imperfect, as long as total errors per codeword stay under the code's correction bound.

- 適用条件: A CTF 'prove you are not a bot/OCR-resistant' or large-binary-distribution challenge where a single declared artifact exceeds the web-fetch tool's per-request byte cap, and/or where raw data is deliberately obfuscated as many small rendered image tiles; an accompanying script defining a custom finite-field/error-correcting-code scheme is the strongest signal to implement that exact decoder rather than guessing a simpler encoding.

### Point-cloud re-rendering for disputed handwritten/overlay OCR（成功） — [出典](ksnctf/34-are-you-human.md)

When reading a small, rotated, noisy rendered text overlay by eye repeatedly gives inconsistent results (ascender vs no-ascender, case ambiguity) across independent passes, stop trusting single blurry resampled image crops. Instead isolate the text's distinctive color/mask pixels, rotate the raw point coordinates analytically (not by resampling a raster), and render the result as a clean point-cloud scatter image with zero interpolation blur and no background clutter; relative glyph height/weight comparisons against unambiguous anchor letters become decisive rather than subjective.

- 適用条件: Any task requiring confident character-by-character transcription of small, rotated, or distorted rendered text (CAPTCHA-style overlays, watermarks, stylized fonts) where ordinary image crops/zooms leave case or letter-identity genuinely ambiguous and repeated guesses have failed.

### Dictionary attack across many weak-password hashes, combine by first letter（成功） — [出典](ksnctf/14-john.md)

A set of many password hashes (sha512crypt/$6$) can each individually be weak (crackable against a modest challenge-specific wordlist) while the real secret is not any single password but a combination rule across all of them (e.g. first letter of each cracked word in a fixed user order). Verifying the combination rule against an expected prefix (e.g. the platform's known flag prefix) is a strong, decisive confirmation signal before submitting.

- 適用条件: A challenge presents many shadow-style hashes plus a pointer to a challenge-specific dictionary (sometimes disguised as a fake extra hash line). sha512crypt may not be available via the host's libc (e.g. macOS); verify any from-scratch implementation against a trusted reference (openssl passwd -N) before trusting negative crack results.

### Self-referential OpenSSL passphrase-from-file: exact truncation and brute-forced unknown header bytes（成功） — [出典](ksnctf/38-canned-can-opener.md)

When a file is OpenSSL-encrypted using its own plaintext bytes as the '-pass file:' password, the usable password is only the bytes up to the FIRST of either a newline (0x0A) or an embedded NUL (0x00), not just the first line by naive newline-splitting; verify this truncation rule and the exact PBKDF2 parameters (digest, iteration count, salt location, derived-key/iv split) against the real openssl CLI on toy inputs before trusting any derived password. When the original file isn't available but a related reference file sharing the same fixed header structure is, reconstruct the password template from that reference and brute-force the few bytes that legitimately vary between the two files (e.g. an EXIF/APPn segment length field) with an in-process KDF+single-block decrypt check across the full small search space, rather than guessing a single value.

- 適用条件: A crypto/forensics challenge where a file is encrypted using a derivative of its own content as the key material, especially via a CLI tool's 'read password from file' option; applicable whenever the exact byte-level truncation/parsing convention of that option is unstated and must be empirically verified rather than assumed from documentation alone.

### shadow ハッシュの辞書攻撃（成功） — [出典](ksnctf/14-john.md)

sha512crypt を配布辞書の単語で総当たりし全アカウントを復元する。

- 適用条件: 辞書が配布され、パスワードが辞書語であること。

### 復元パスワードの頭文字連結（成功） — [出典](ksnctf/14-john.md)

復元した語列の頭文字を順に並べて隠れた文字列を得る。

- 適用条件: 先頭が既知の接頭辞 (FLAG_) になること。

### ハッシュ照合と既知プレフィックスからの鍵 (識別子) 総当たり（成功） — [出典](ksnctf/15-jewel.md)

鍵が短い数字識別子 (IMEI) 由来で、そのハッシュと一部桁が既知の場合、残り桁を列挙してハッシュ一致で鍵を復元し AES-CBC で復号する。

- 適用条件: 探索空間が 10^7 程度以下、チェックサム桁 (Luhn) で更に削減可能

### 既知の素因数によるRSA復号（成功） — [出典](ksnctf/16-math-i.md)

p,qからd=e^-1 mod phiを求めpow(c,d,n)でメッセージを得る。

- 適用条件: nの素因数が既知でeがphiと互いに素

### 厳密なべき乗の整数k乗根（成功） — [出典](ksnctf/17-math-ii.md)

大整数を二分探索でk乗根にし、再べき乗で完全一致を検証する。

- 適用条件: 法付きではなく整数として与えられた完全べき乗

### 独自GF(256)実装のReed-Solomon復号（成功） — [出典](ksnctf/34-are-you-human.md)

ソースの要素表現（バイト=指数）と符号語の並び（パリティが低次）、生成多項式の根(α^0..α^190)を読み取り、シンドローム→BM→Chien→Forneyで復号し残余シンドロームで検証する。

- 適用条件: 符号パラメータと多項式表現が配布ソースから読める。誤り数が訂正限界以内

### MT19937 状態復元による鍵ストリーム予測（成功） — [出典](ksnctf/21-perfect-cipher.md)

既知平文XORで得た連続出力を untemper して624語で状態復元し、後続の鍵ストリームを生成して別ファイルを復号する。

- 適用条件: 同一MTインスタンスの出力が連続して鍵に使われ、連続624ワード分の平文が既知であること。

### 状態誤差の逆算補正（成功） — [出典](ksnctf/21-perfect-cipher.md)

既知平文が一部不正確でも、後続平文の既知領域(零パディング等)での誤差パターンからMT漸化式を逆に辿って状態誤差を復元する。

- 適用条件: 後続ストリームに既知(零など)の領域が十分あり、誤差が疎であること。

### ROT13の識別と復号（成功） — [出典](ksnctf/2-easy-cipher.md)

文中の 'EBG KVVV' など頻出語のROT13像から換字式シーザー暗号を推定し復号

- 適用条件: 英文らしい換字暗号文

### 視覚暗号シェアの XOR 合成（成功） — [出典](ksnctf/28-lo-tech-cipher.md)

複数の2値画像を画素ごとに XOR/AND して隠し画像を復元。途中結果の文字ヒントで不足シェアを推定する。

- 適用条件: 同サイズの白黒ノイズ画像が複数ある

### RSA共通素因数(gcd)による複数証明書の鍵復元（成功） — [出典](ksnctf/33-https-is-secure.md)

複数のRSA公開鍵の法同士のgcdを取り、1より大きければ共通素因数から双方の秘密鍵を計算する。

- 適用条件: 同一素数を共有する2つ以上のRSA公開鍵が入手できる

### ZipCrypto 既知平文攻撃(Biham-Kocher)（成功） — [出典](ksnctf/19-zip-de-kure.md)

連続12バイト以上の既知平文から内部鍵3個を復元し、パスワードなしで同一パスワードの全エントリを復号する。

- 適用条件: 従来型ZipCrypto、既知平文12バイト以上(うち連続8以上)

### Shared-prime RSA factoring by GCD（成功） — [出典](alpacahack-daily/shared-prime-shared-prime.md)

If two RSA moduli share a prime factor, gcd(n1,n2) recovers it instantly; divide out to get the other factors and decrypt.

- 適用条件: Two moduli generated with a common prime.

### Continued-fraction recovery of near-shared RSA primes（成功） — [出典](alpacahack-daily/almost-share-almost-shared-prime.md)

Given n1=p*q1 and n2=(p+2)*q2 with small q1,q2, the ratio n2/n1 = (q2/q1)*(1+2/p) differs from q2/q1 by ~2/p, far below 1/(2*q1^2). By Legendre's theorem q2/q1 (lowest terms) is a convergent of the continued fraction of n2/n1; the convergent whose denominator divides n1 and has the right bit-length yields q1, hence p.

- 適用条件: Two RSA moduli sharing a prime up to a small known additive shift, with the co-factors much smaller than the shared prime.

### Pollard p-1 with a disclosed smooth structure (per-candidate split)（成功） — [出典](alpacahack-daily/yell-yell.md)

When p-1 and q-1 are products of KNOWN small primes (disclosed by the challenge) times a tiny cofactor, a plain Pollard p-1 over all of them yields gcd=n (both sides smooth). Split instead: for each disclosed prime x compute gcd(2^(E/x)-1, n) with E=lcm(1..B)*prod(primes); if x divides only p-1 the gcd reveals one factor.

- 適用条件: RSA where the prime factors of p-1/q-1 are leaked (e.g. printed) and shared across both primes.

### Recover two values from their power sums (p1,p2)（成功） — [出典](alpacahack-daily/sigma-secret-secret-sigma.md)

Given s1=x+y and s2=x^2+y^2, xy=(s1^2-s2)/2, so x,y are the roots of t^2 - s1 t + xy = 0; pick the root in the expected range. Used to invert a per-block 'sum of k-th powers' encoding.

- 適用条件: An encoding that leaks symmetric power sums of a small number of unknowns per block.

### Franklin-Reiter related-message attack（成功） — [出典](alpacahack-daily/bitflip-rsa-bitflip-rsa.md)

同一の n,e で線形関係 (m と a*m+b) にある2平文の暗号文があれば、x^e-c1 と (ax+b)^e-c2 の多項式GCDを mod n で取ると一次式になり平文が復元できる。e が小さい(~101程度まで)場合に実用的。

- 適用条件: 同一モジュラス・同一小さい指数、平文間に既知の線形関係(ビット反転 ~m = -m-1 など)。

### Recover cyclically shared near-prime factors via sqrt of modulus ratio（成功） — [出典](alpacahack-daily/neighborhood-neighborhood_distance.md)

When moduli are n1=p*q', n2=q*r', n3=r*p' with x' a small distance from x, n1*n3/n2 is approximately p^2 with relative error about 2^-(bits-16). Integer sqrt gives p within a small window; scan the window for a divisor of n1, then repeat cyclically for q and r.

- 適用条件: Several RSA moduli built from a cycle of primes where each co-factor is next_prime of another prime (small gap), so the ratio approximation error is much smaller than the prime size.

### CTR counter wraparound to reuse a forbidden keystream（成功） — [出典](alpacahack-daily/settable-counter.md)

When a CTR service forbids re-using the counter values used for a secret only by a lower-bound check, set the counter to the maximum value of the counter field so it overflows back to zero; encrypting known zeros then yields the secret's keystream (skip the blocks before the wrap).

- 適用条件: Settable CTR initial counter, counter field narrower than the block (e.g. 8-byte nonce + 8-byte counter), library allows wrap except back to its own initial value (pycryptodome).

## forensics

### NTFS deleted-file ADS reassembly（成功） — [出典](ksnctf/18-usb-flash-drive.md)

Recover a payload hidden across multiple named NTFS Alternate Data Streams on a deleted file record, by walking the MFT directly and concatenating each resident ADS's bytes in stream-name order, rather than inspecting the visible unnamed data stream's content.

- 適用条件: Disk/filesystem image forensics tasks where a decoy file explicitly denies hiding data in its visible content, and the filesystem is NTFS so alternate data streams are available as a hiding place; applies when no other on-disk artifact yields the payload.

### NTFS の MFT を直接走査して名前付き $DATA (ADS) を探す（成功） — [出典](ksnctf/18-usb-flash-drive.md)

ブートセクタから MFT 位置を求め、USA fixup 後に全レコードの $DATA 属性を列挙して、名前付きストリームと削除済みレコードを確認する。

- 適用条件: NTFS イメージが配布され、カービングや文字列検索で flag が見つからないとき。

### PNG の tEXt チャンクにあるコメントの確認（成功） — [出典](ksnctf/15-jewel.md)

画像内の文言が示唆するメタデータの場所を PNG チャンク走査で読む。

- 適用条件: 画像に隠し場所のヒントがある

### Password-file truncation brute force（成功） — [出典](ksnctf/38-canned-can-opener.md)

パスワードがファイル先頭行(NUL/改行で切断)になる点と既知ヘッダ構造から未知バイトのみ総当たりし、最初の暗号ブロックのマジック判定で検証する。

- 適用条件: 暗号化鍵が既知形式のバイナリファイルから導出され、一部バイトのみ未知の場合

### 2色ノイズ付きCAPTCHAタイルのクラスタリングOCR（成功） — [出典](ksnctf/34-are-you-human.md)

背景色1色・文字色数色・細いノイズ線のタイルを、最頻色で2値化→2x2 openingで線除去→bbox正規化→k-meansして、モンタージュを目視でラベル付けする。

- 適用条件: フォントが固定で文字高がほぼ一定、ノイズ線が文字より細い

### 生の画素点群の幾何的読み取りによる大文字小文字判定（成功） — [出典](ksnctf/34-are-you-human.md)

特定色の画素を抽出し、PCA主軸で座標を回転（リサンプリングなし）、x方向の隙間でグリフ分割して高さを数値比較する。

- 適用条件: 回転・手書き風の文字で補間画像だと大小が曖昧

### pcap から HTTP Basic 資格情報を抽出（成功） — [出典](ksnctf/8-basic-is-secure.md)

strings/grep で Authorization ヘッダを見つけ base64 デコード

- 適用条件: 暗号化されていない HTTP の通信キャプチャがある

### pcapからのTLS(RSA鍵交換+RC4)手動復号（成功） — [出典](ksnctf/33-https-is-secure.md)

TCP再構成後にPMSをRSA復号し、TLS1.0 PRFでmaster secretとkey blockを導出、RC4でレコードを復号する。session ID再開も同じmaster secretで処理する。

- 適用条件: サーバの秘密鍵が得られ、鍵交換がRSA(非PFS)でハンドシェイクがキャプチャに含まれる

### 切断されたチェックポイントからの重み復元と検証（成功） — [出典](ksnctf/40-deep-flag-network.md)

中央ディレクトリのないzipをローカルヘッダから走査し、重みの並び順を候補で探索して公開出力と照合しレイアウトを確定する。

- 適用条件: zipがEOCDなしで切断されている。variables.indexが欠落している。公開された推論結果が手元にある。

### 中央ディレクトリ欠落ZIPの手動展開（成功） — [出典](ksnctf/29-double-blind.md)

ローカルファイルヘッダを順に読みdeflateを展開する

- 適用条件: EOCDが無くunzipが失敗するOOXML

### OOXML内の画像descr属性の確認（成功） — [出典](ksnctf/29-double-blind.md)

document.xmlのdocPr descrに残る作成環境パスを調べる

- 適用条件: docPropsが削除された文書

## misc

### 空白ポリグロットの Whitespace 解釈（成功） — [出典](ksnctf/7-programming.md)

ソースの空白・タブ・改行だけを抽出し Whitespace インタプリタで実行、比較定数から入力を得る

- 適用条件: ソースに大量の不自然な空白があり、通常言語の出力が偽物に見える

### 文字ケースで符号化された1ビット画像(QR)の検出（成功） — [出典](ksnctf/22-square-cipher.md)

格子状テキストの大小文字マスクを可視化し、角の7x7パターンからQRと判定、形式情報で版・誤り訂正・マスクを特定してデコードする。

- 適用条件: 正方格子で大小文字の配置に空間的構造がある。

### 定数の桁列から条件を満たす部分列を探索（成功） — [出典](ksnctf/20-g00913.md)

任意精度整数でπの桁を生成し、固定長の窓ごとにMiller-Rabinで素数判定して最初のものを取る。

- 適用条件: 桁列の生成法と数え方(整数部を含むか)が問題文から確定できること。

### 問題文中のフラグ抽出（成功） — [出典](ksnctf/1-test-problem.md)

HTMLからタグを除去しFLAG形式の文字列を正規表現で取り出す

- 適用条件: フラグが本文に直接書かれている

### 多重Base64の自動剥離とuuencode（成功） — [出典](ksnctf/5-onion.md)

Base64として妥当な限り反復デコードし、'begin 666' を見つけたらuudecodeする

- 適用条件: Base64の入れ子で先頭が 'Vm0w' などの定型

### クォート演算子の区切り文字による字句解析（成功） — [出典](ksnctf/25-reserved.md)

q や qw の直後の空白と任意の 1 文字を区切りとして読み、予約語列を式の並びに戻す

- 適用条件: 予約語列が q や qw を含み、区切り文字が空白の直後に置かれている

### 関数鎖の内側からの静的評価（成功） — [出典](ksnctf/25-reserved.md)

print chr の後ろの変換関数を右から左へ適用し、1 文字ずつ出力を組み立てる

- 適用条件: 出力文が chr と変換関数の連鎖で書かれ、末尾に値がある

### PNG+ZIP polyglot からの追加シェア発見（成功） — [出典](ksnctf/28-lo-tech-cipher.md)

拡張子がzipでも実体がPNGで、ZIPが末尾連結されている場合、外側ファイル自体も素材として扱う。

- 適用条件: file が画像と判定しつつ zipfile でも開ける

### 活性化なしネットワークの一次写像への畳み込み（成功） — [出典](ksnctf/40-deep-flag-network.md)

Denseと推論時BatchNormだけの層は逆伝播で入出力の線形写像を求められ、ロジットを入力の一次式として扱え、勾配計算が単純になる。

- 適用条件: 隠れ層に非線形活性化がない。BatchNormが推論モードで使われている。最終層がSoftmaxのみ。

### ファイル形式のマジックバイトを既知平文に使う（成功） — [出典](ksnctf/19-zip-de-kure.md)

暗号化アーカイブ内の JPEG/PNG 等は先頭ヘッダが固定なので既知平文として使える。

- 適用条件: 暗号化エントリが無圧縮(stored)で先頭位置が分かる

### 自作攻撃コードの合成データ検証（成功） — [出典](ksnctf/19-zip-de-kure.md)

既知パスワードで生成した合成サンプルに対し攻撃を限定範囲で走らせ、復元鍵が一致することを確認してから本番を回す。

- 適用条件: 探索が長時間になる自作ツール

### jjencode系難読化の静的デコード（成功） — [出典](ksnctf/3-crawling-chaos.md)

識別子表と true/false/[object Object]/undefined の文字列インデックスから文字テーブルを再構築し、連結したペイロードを実行せずに展開する

- 適用条件: 記号/特殊識別子のみで構成されたJS、実行禁止環境

### 線形チェックの逆算（成功） — [出典](ksnctf/3-crawling-chaos.md)

入力文字コード×位置 = 定数配列 の検査を除算で逆算して入力を復元する

- 適用条件: 検証式が可逆な算術で与えられている

### 活性化なしNNのモデル反転（成功） — [出典](ksnctf/40-deep-flag-network.md)

線形層とBNのみのネットワークをアフィン写像として扱い、目的クラス確率を最大化する入力を求める

- 適用条件: 重みが入手可能で非線形活性化がない

### 構造制約付きビット探索とRS訂正によるQR復元（成功） — [出典](ksnctf/40-deep-flag-network.md)

QRの機能パターンを固定し、モデルの対数確率を貪欲反転で最適化、残る誤りをReed-Solomonで訂正

- 適用条件: 復元対象がQRコードと推定でき、サイズ・位置を総当たりできる

### 改行禁止・UTF-8必須の制約下での pickle RCE payload 整形（成功） — [出典](alpacahack-daily/tsukemono-lo-tsukemono-loader.md)

input() 由来のテキスト入力を encode() して pickle.loads に渡すサービスでは、payload に改行を含められず、かつ全体が妥当なUTF-8である必要がある。protocol0 の改行終端 GLOBAL を避け STACK_GLOBAL(0x93)+BINUNICODE で関数を解決し、直前の BINPUT 等の引数バイトを UTF-8 継続バイト(0x80-0xBF)に選んで後続オペコードと妥当なマルチバイト文字を構成することで UTF-8 制約を満たす。生成後に『改行なし』『strict UTF-8 デコード可』を静的検証してから送る。

- 適用条件: pickle.loads(input(...).encode()) 形式で、1行読み＋テキストエンコード（特に Python 3.11+ / UTF-8 mode デフォルトの環境）によりバイト列に制約が課される場合。

### Shell command injection without spaces using ${IFS}（成功） — [出典](alpacahack-daily/cowsay-jail-cowsay-jail.md)

When input is interpolated into a shell command with shell=True but spaces and many metacharacters are denied, use ${IFS} in place of spaces and ';' to chain commands (both often missed by deny lists). e.g. `x;cat${IFS}/flag`.

- 適用条件: shell=True command interpolation with a character deny list that forgets ; $ { }.

### No-builtins pyjail under strictly-decreasing token-length constraint（成功） — [出典](alpacahack-daily/decreasing-decreasing.md)

Reach the real builtins dict from a literal via ().__reduce_ex__(2)[0].__builtins__ (copyreg function carries real builtins). Satisfy exotic lexical filters (e.g. every \w+ token must be strictly shorter than the previous) with digit-free integers built from comparisons ( ()==() ->1, ()>()->0, -~(()==())->2 ) and by padding a key as 'x__import__'[1:] to fit a length slot; then __import__('subprocess').run(['sh']) and drive the spawned shell via later stdin lines (send them after a delay so the jail's input() does not buffer-steal them).

- 適用条件: eval with empty __builtins__ plus a lexical filter on token lengths/ordering.

### Recover a secret via a base64-validity oracle（成功） — [出典](alpacahack-daily/remnant-remnant.md)

If a service XORs your input with a secret and only reveals whether base64decode succeeds, you get one validity bit per query. With non-strict b64decode (which drops non-alphabet bytes) you can mask all but one position to filler and binary-search the single counted byte over the 65 alphabet candidates, recovering the secret byte by byte.

- 適用条件: An oracle that leaks only success/failure of decoding a function of your input XOR a fixed secret.

### Code execution via Lean #eval at elaboration time（成功） — [出典](alpacahack-daily/lean-as-a-se-lean-as-a-service.md)

`lean Main.lean` runs #eval terms during elaboration and prints their output. An `#eval (do ... : IO Unit)` can perform arbitrary IO (IO.FS.readDir/readFile, IO.Process.run) to read a flag file; output is returned by any service that echoes compiler stdout.

- 適用条件: A service that compiles/checks attacker-supplied Lean source and returns stdout/stderr.

### Count items across paginated calendar views（成功） — [出典](alpacahack-daily/quiz-alpacas-quiz-alpacashock.md)

When a question asks for a cumulative count over a calendar-style listing, fetch each period via the site's own query parameter, de-duplicate multi-day cells and boundary padding from adjacent months, and sum per period.

- 適用条件: A quiz-style challenge whose answer is derivable from public listing pages and the listing supports period selection.

### Empty-string find bypass（成功） — [出典](alpacahack-daily/vending-machine-revised-version.md)

find/in による検証は空文字列で常に成功することを利用する

- 適用条件: 入力を str.find や in で検証するサービス

### f-string chr generation to bypass character blacklist（成功） — [出典](alpacahack-daily/nested-eval.md)

f-string の {N:c} で禁止文字を生成し、二重 eval で実行させる

- 適用条件: eval 系の jail で文字ブラックリストがある

### INT_MIN divided by -1 trap（成功） — [出典](alpacahack-daily/integer-division.md)

符号付き最小値を -1 で割ると idiv が #DE を起こしプロセスが SIGFPE で落ちる

- 適用条件: 0除算だけを検査する C プログラム

### reboot syscall magic numbers（成功） — [出典](alpacahack-daily/lets-shut-down-linux-let-s-shut-down-linux.md)

reboot(2) は magic1/magic2 が正しく cmd=POWER_OFF のとき停止する。man 2 reboot の定数を10進で渡す

- 適用条件: reboot システムコールの引数を指定させる問題

### Call without parentheses via __class_getitem__ assignment（成功） — [出典](alpacahack-daily/no-parentheses-o.md)

内包表記ターゲットで Python 製クラスの __class_getitem__ に eval を代入し、Cls[文字列] で呼び出す。内側コードの括弧は \x28/\x29 で生成する

- 適用条件: eval ベースの jail で括弧が除去/禁止されている。モジュール内に Python 製クラスが到達可能

## pwn

### printf leak -> libc base -> environ for stack secrets（成功） — [出典](alpacahack-daily/what-is-my-p-what-is-my-pointer-2.md)

An arbitrary-read primitive plus a leaked libc function pointer lets you compute the libc base (leak - symbol_offset), then read the libc `environ` global (base + environ_offset) to obtain the stack address of the envp array, walk it, and read any environment string (e.g. a flag passed via an env var). Offsets come from the exact target libc, which for a pinned Docker base can be extracted from that image.

- 適用条件: A loop/arbitrary read where you supply an address and get its contents, a leaked libc pointer, and a secret stored in the environment or elsewhere reachable from a libc global.

### malloc(huge)->NULL then OOB index for absolute read（成功） — [出典](alpacahack-daily/what-is-my-p-what-is-my-pointer-4.md)

When malloc(size) fails it returns NULL; a subsequent arr[index] then dereferences index*sizeof(elem) as an absolute address. Combined with a leaked target address, pick index=target//8 to read an arbitrary 8-byte-aligned word. If only one read per connection is allowed, reconnect and reassemble the secret across connections using each connection's fresh leak and known alignment.

- 適用条件: User-controlled allocation size that can force NULL, an unchecked signed index into the returned pointer, and a leaked absolute address of the secret.

### arch_prctl(ARCH_SET_FS) to relocate the stack-canary source（成功） — [出典](alpacahack-daily/fsbase-modif-fsbase-modification.md)

If the program lets you set the FS base (arch_prctl ARCH_SET_FS) before a canaried function runs, the canary read at %fs:0x28 comes from an attacker-chosen address. Point FS so that FS+0x28 falls on a qword whose value you know (e.g. a zero-initialised .bss slot in a no-PIE binary => canary 0). Then a stack overflow can overwrite the return address past a 'known' canary and ret2win.

- 適用条件: User-controlled FS base via arch_prctl before a stack-protected vulnerable function, plus a stack buffer overflow and a win()/one-gadget.

### Leak AT_RANDOM via getauxval to recover the stack canary（成功） — [出典](alpacahack-daily/auxiliary-ve-auxiliary-vectors-are-our-friends.md)

glibc derives __stack_chk_guard from the 8 bytes at the AT_RANDOM auxiliary vector (with the least-significant byte forced to 0x00). If the program exposes getauxval(type) and lets you read memory at the returned pointer, query AT_RANDOM (25), read its 16 bytes, and the canary is bytes[0:8] with byte0 zeroed. Then overflow past the known canary to ret2win.

- 適用条件: A primitive that returns getauxval(user_type) and reads memory at that address, plus a canaried stack overflow and a win gadget.

## rev

### Android IMEI-gated AES-CBC resource decryption（成功） — [出典](ksnctf/15-jewel.md)

An Android app gates a secret by checking a device identifier's prefix and its SHA-256 hash against hardcoded constants, then uses a key derived from that same identifier plus a hardcoded IV to AES/CBC/PKCS5 decrypt an embedded raw resource. Brute-forcing the unknown suffix of the identifier against the hardcoded hash (small search space) recovers the full identifier, which then unlocks the decryption key directly from the disassembled bytecode's constant construction order.

- 適用条件: Dalvik/APK reverse engineering where a hash check gates a partially-known identifier (IMEI, serial, device id) with only a short unknown portion, and bytecode disassembly reveals how a key/IV pair is built from that identifier plus a hardcoded string for decrypting an embedded asset (image, resource) that holds the final secret, e.g. in a metadata/text chunk.

### 最小限の dex 逆アセンブラによる Android ロジック復元（成功） — [出典](ksnctf/15-jewel.md)

dex のヘッダから文字列/型/メソッド表を読み、Dalvik 命令長表で命令列を走査して定数文字列と呼び出し先を注釈付きで出力する。

- 適用条件: apk/dex があり baksmali・jadx 等が使えない環境

### 埋め込みRC4鍵と暗号文の静的復号（成功） — [出典](ksnctf/11-riddle.md)

x86 PEを逆アセンブルしRC4ループを特定、鍵と比較用暗号文をデータ領域から抽出して復号する。

- 適用条件: 鍵と暗号文が同一バイナリ内にあり、比較用構造体の配置が読み取れる

### .NET IL静的解析で比較対象配列を鍵として復号（成功） — [出典](ksnctf/24-rights-out.md)

ILを逆アセンブルして check ロジックを特定し、同一アセンブリ内の静的配列をXOR鍵・暗号文として取り出し、既知接頭辞で位置合わせして復号する。

- 適用条件: .NET実行ファイルで鍵・暗号文が静的配列として埋め込まれている。

### 勝利条件後の出力生成ルーチンを静的に再現（成功） — [出典](ksnctf/27-lives-out.md)

パズル解答に依存しない定数配列からの文字列生成処理を逆アセンブルで特定し、Pythonで同じ演算を再現して出力を得る。

- 適用条件: 出力生成が入力や乱数に依存せず定数のみで決まる場合

### rip相対のSSE定数コピーをcapstoneで自動抽出（成功） — [出典](ksnctf/27-lives-out.md)

movdqaのrip相対ロードとスタック保存を追跡し、スタック上に構築される定数配列をファイルから復元する。

- 適用条件: x64バイナリで定数がmovdqa経由でスタックへコピーされる場合

### 英数字限定シェルコードのデコーダを自前再実装（成功） — [出典](ksnctf/30-alpha-mixed-cipher.md)

自己書換えを含むALPHA2系デコードループをPythonで再現し、実行せずに平文シェルコードを得て逆アセンブルする。

- 適用条件: 英数字のみのx86ペイロードでデコードループが特定できる場合

### パラメータ総当りと可読文字列で復号検証（成功） — [出典](ksnctf/30-alpha-mixed-cipher.md)

開始位置や乗数を総当りし、出力中に文字列やAPI名が現れるかで正しいデコード方式を判定する。

- 適用条件: デコーダの細部が曖昧で、平文に文字列が含まれる場合

### Recover expected input from an embedded base64+Brotli blob（成功） — [出典](alpacahack-daily/csharp-file--c-file-based-app.md)

A checker that compares your input to decompress(base64decode(const)) is inverted by decoding that constant directly (base64 then Brotli), no execution needed.

- 適用条件: A comparison checker whose target is a compressed constant in the source/binary.

### Invert a per-pair MD5 flag checker by brute force（成功） — [出典](alpacahack-daily/x32-abi-flag-x32-abi-flag-checker.md)

If each flag byte-pair is hashed (MD5 of a small transform) and compared to a table, brute-force all 65536 pairs for each table entry; a unique match per entry that chains consistently reconstructs the flag.

- 適用条件: A checker that hashes small (<=16-bit) chunks of the input against a fixed table.

### Static decode of a .pyc whose key is derived from its own location（成功） — [出典](alpacahack-daily/typhoon-pyth-typhoon-pythoon.md)

Load the pyc with marshal under the matching Python version, disassemble with dis, and read the constants of the location check and the decode routine. Reimplement the decode with the required directory name instead of running the program.

- 適用条件: A compiled Python file refuses to run unless placed in a specific directory and derives its expected answer from that directory name.

### x87 fsin out-of-range operand passthrough（成功） — [出典](alpacahack-daily/sin-function-vs-fsin-instruction-sin-function-vs.-fsin-instruction.md)

fsin は |x|>=2^63 の引数を変更せず返すため、大きな有限値で libm の sin と大きく乖離する

- 適用条件: fsin と sin の結果を比較するプログラムが大きな有限 double を受け付ける
