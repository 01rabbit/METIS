# Digest is secure!

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 9 |
| カテゴリ | web |
| 配点 | 150 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | web, pcap, digest |
| 問題URL | https://ksnctf.sweetduet.info/problem/9 |
| METIS run | `c9b692b4b97b44948d1834786955e4e0` |

## 概要

pcap を解析し、2 回の scoped web request が成功せず止まった。

## 解析

q9.pcap を overview / pcap / strings で解析した（pcap は 2 回）。続けて scoped_web_requests を 2 回送ったが、いずれも requests=1, succeeded=0 で tool_ok=false だった。（イベント記録上、これ以外の試行は残っていない）

## 解法

未解決。flag 候補なし。pcap から得た情報を使った再現リクエストが通らず、先へ進めなかった。

## 学び・再利用できる手法

次は pcap 内の認証ヘッダを改めて整理し、通らなかった原因（URL、認証、期限）を切り分ける。


## METISの記録

- 期間: 2026-11-12 23:48 JST 〜 2026-11-13 13:41 JST
- 使用アクション数: 6（read_only_artifact_analysis ×4, scoped_web_requests ×2）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 8,560 | `ea886782351c42aabe16896dbc1b937d1c594a9f4166a0be48969271239a1831` |
| 01-00-q9.pcap | 4,821 | `e98c34c10fee2427701c19b18f39559b359426d4a912b28adfbc016ee228509b` |

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
