# Villager B

| 項目 | 内容 |
| --- | --- |
| 大会 | ksnctf |
| 問題番号 | 23 |
| カテゴリ | pwn |
| 配点 | 450 |
| 状態 | ブロック中 |
| Flag | - |
| タグ | pwn, pie, canary, relro |
| 問題URL | https://ksnctf.sweetduet.info/problem/23 |
| METIS run | `1324361dd312490c8b5babbe51f7f25a` |

## 概要

PIE / stack protector / RELRO 有効の pwn 問題。解析を重ねたが、予算上限で 2 回停止した。

## 解析

問題文は PIE、-fstack-protector-all、RELRO（now）、xinetd 経由、ブルートフォース対策の待ち時間を挙げる。記録上の操作: text 4、overview 3、elf 3、disassemble 18、strings 1、hex 1、sandbox 内の script 実行 6、scoped web request 2（成功）、remote service exchange 2（受信は空）。budget_limit で 2 回 exhausted になり、operator_budget_extension で 2 回続行した。観測のうち 11 回が tool_ok=false。

## 解法

未解決。flag 候補なし。flag 候補は得られていない。リモート側の応答が空で、サービスとの対話が成立しなかった。

## 学び・再利用できる手法

次は逆アセンブルの結果から canary / PIE のリーク経路を整理し、ローカルで再現してから対話を再開する。


## METISの記録

- 期間: 2026-11-13 11:59 JST 〜 2026-11-13 15:55 JST
- 使用アクション数: 40（read_only_artifact_analysis ×30, remote_service_exchange ×2, sandboxed_dynamic_execution ×6, scoped_web_requests ×2）

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 9,394 | `57bbc6e0db18d38bb330ace74c83405616d8fe8dfbdb4c63480665d62045b10a` |
| .metis-web/b6b6bd2322cb47769915cb0dc61dca8f.bin | 7,515 | `5983717aa35400236d1ba5c0ce17df7ab8caf7e345aae6cc71a6466740daa010` |
| .metis-web/ef139ab5f7a8402cbcfd59eba1b5c95f.6 | 2,840,668 | `f4719bcfa0262d8e3bd00683441a4c52b6f63a30fd37c6eb636218976906fcd3` |

### 接続先

- ctfq.u1tramarine.blue:10023

<sub>METIS writeup — 更新: 2026-11-13 17:39 JST</sub>
