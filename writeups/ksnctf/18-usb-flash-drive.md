# USB flash drive

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 18 |
| カテゴリ | forensics |
| 配点 | 80 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 13:39 JST） |
| Flag | `FLAG_qazyetF6icoWCvjN` |
| タグ | forensics, ntfs, mft, alternate-data-stream, deleted-file |
| 問題URL | https://ksnctf.sweetduet.info/problem/18 |
| METIS run | `260f0c6cf21a4b019cb65d168bcb3163` |

## 概要

配布の drive.img (NTFS, 16MiB) の削除済み MFT レコード 36 に付いた名前付き $DATA ストリーム (Alternate Data Stream) 7 本 '00'〜'06' を順に連結すると flag になる。

## 解析

配布物は drive.img を 1 つ含む zip。ブートセクタは OEM 'NTFS'、512B/sector、8 sectors/cluster、$MFT は LCN 1365、レコード長 1024B。MFT を走査すると JPEG (carl, liberty, mona, wave) が見つかるが、どれも FFD9 で終わり、末尾データや 'FLAG' 文字列は無い。そこで削除済みレコードの属性を全て調べた。レコード 36 (flags=0、削除済み、'Liberty Leading the People.jpg') は、通常の non-resident な無名 $DATA (173276B) の他に、名前付きの resident $DATA を 7 本持っていた。他のレコードに名前付き $DATA は無い。ストリーム内容は 3 バイトずつの断片。

## 解法

1. zip から drive.img を取り出す。
2. ブートセクタから bytes/sector=512、sectors/cluster=8、$MFT の LCN=1365 を読み、MFT のレコード (1024B) を順に走査する。update sequence array (USA) の fixup を適用する。
3. 全レコードの 0x80 ($DATA) 属性を列挙し、名前付きストリームを探す。
4. レコード 36 の名前 '00'〜'06' の resident $DATA を名前の昇順に連結する。

```python
import zipfile, struct
img = zipfile.ZipFile(zpath).read('drive.img')
bps, spc, rsize = 512, 8, 1024
mft_off = 1365 * bps * spc
# fix(): USA fixup、attrs(): 属性列挙、aname(): 属性名 は 18-ads.py 参照
r = fix(img[mft_off + 36*rsize: mft_off + 37*rsize])
parts = {name: data for (name, data) in resident_named_data(r)}
flag = b''.join(parts[k] for k in sorted(parts)).decode()
```

ストリームの内容は順に FLA / G_q / azy / etF / 6ic / oWC / vjN で、連結すると flag になる。

## 使用したスクリプト

- [18-inspect.py](files/18/18-inspect.py)
- [18-ntfs.py](files/18/18-ntfs.py)
- [18-ads.py](files/18/18-ads.py)
- [18-carve.py](files/18/18-carve.py)

## 学び・再利用できる手法

ファイルシステムイメージでは、ファイルの中身だけでなく MFT の属性 (ADS、削除済みレコード) まで調べる。通常のファイル一覧やカービングでは名前付きストリームは見えない。また、削除済みレコードは flags=0 になるだけで内容が残る。公式提出と照合するときは、METIS の web_attempts のダイジェストが run ごとの salt を使った HMAC-SHA256 であることに注意する (単純な sha256 とは一致しない)。この flag は HMAC で受理済みダイジェストと一致することを確認した。

- **NTFS の MFT を直接走査して名前付き $DATA (ADS) を探す**（forensics）: ブートセクタから MFT 位置を求め、USA fixup 後に全レコードの $DATA 属性を列挙して、名前付きストリームと削除済みレコードを確認する。
  - 適用条件: NTFS イメージが配布され、カービングや文字列検索で flag が見つからないとき。

## METISの記録

- 期間: 2026-11-13 13:37 JST 〜 2026-11-13 13:39 JST
- 使用アクション数: 2（official_flag_submission ×1, scoped_web_requests ×1）
- 判定方式: official_ksnctf

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 13:39 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,601 | `2c2ab3dc64c848cf25ab5f17ded1cb02f0d1f86d5920057bbbeeb624aa7053b2` |
| 01-00-drive.zip | 605,795 | `514b9394ed7adcf5608b2bc66fe0e8d4885a2804298a4f0c21c56b4fb4d01a24` |
| .metis-web/4b58742f502649a6af0aa671f0e0cff9.zip | 605,795 | `514b9394ed7adcf5608b2bc66fe0e8d4885a2804298a4f0c21c56b4fb4d01a24` |

<sub>METIS writeup — 更新: 2026-11-13 15:50 JST</sub>
