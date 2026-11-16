# Remnant

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | remnant |
| カテゴリ | misc |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-13 21:00 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/remnant-remnant.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | misc, oracle, base64 |
| 問題URL | https://alpacahack.com/daily/challenges/remnant |
| METIS run | `a6af73464af040ce82dcc0ecebca8255` |

## 概要

b64decode(XOR(flag,x)) の成否オラクルで flag(base64) を逐byte復元し、復号して内側フラグを得る。

## 解析

validate=False の b64decode は非英数字を落とす。前方確定分を落とし文字に、対象1バイトのみ候補65個を二分探索。

## 解法

オラクル問い合わせで base64 文字列復元 -> base64decode -> ⟦answer:writeups/alpacahack-daily/remnant-remnant.md#1⟧（最後に flag 自体を送って Correct! 確認）。

## 使用したスクリプト

- [remnant-solver.py](files/remnant/remnant-solver.py)

## 学び・再利用できる手法

b64decode(XOR(flag,x)) の成否オラクルで flag(base64) を逐byte復元し、復号して内側フラグを得る。

- **Recover a secret via a base64-validity oracle**（misc）: If a service XORs your input with a secret and only reveals whether base64decode succeeds, you get one validity bit per query. With non-strict b64decode (which drops non-alphabet bytes) you can mask all but one position to filler and binary-search the single counted byte over the 65 alphabet candidates, recovering the secret byte by byte.
  - 適用条件: An oracle that leaks only success/failure of decoding a function of your input XOR a fixed secret.

## METISの記録

- 期間: 2026-11-13 20:31 JST 〜 2026-11-13 21:00 JST
- 使用アクション数: 3（official_flag_submission_browser ×1, remote_service_solver_pipe ×1, scoped_web_requests ×1）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-13 21:00 JST | correct | 1 |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 375,502 | `fdfe88a654ace38e8b4edb26121eafb8865ec7a6ad92b173aa78742c1417298f` |
| 01-00-remnant.tar.gz | 606 | `5c296141da1c2bf1f287fc98198bf6eebdb3eaee2697c77e3f7fdfedcf13c3cd` |
| .metis-web/72b5fd2347cb4655896eed54f8f0344e.gz | 606 | `5c296141da1c2bf1f287fc98198bf6eebdb3eaee2697c77e3f7fdfedcf13c3cd` |
| .metis-remote/6596cb17195b4ba2a4c246c0209919f7.recv | 2,643 | `5587257d45824188395632ad2cd02bd2c5750cae9256a400e8590387f1ad4c04` |

### 接続先

- 34.170.146.252:25100

<sub>METIS writeup — 更新: 2026-11-13 21:19 JST</sub>
