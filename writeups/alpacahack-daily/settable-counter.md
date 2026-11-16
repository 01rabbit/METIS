# settable counter

| 項目 | 内容 |
| --- | --- |
| 大会 | AlpacaHack Daily |
| 問題番号 | settable-counter |
| カテゴリ | crypto |
| 配点 | 1 |
| 状態 | 解決済み（公式判定で正解: 2026-11-16 09:11 JST） |
| Flag | `⟦answer:writeups/alpacahack-daily/settable-counter.md#1⟧` |
| Flag照合 | 公式判定で正解した文字列と一致 |
| タグ | crypto, AES, CTR, counter-wraparound, keystream-reuse |
| 問題URL | https://alpacahack.com/daily/challenges/settable-counter |
| METIS run | `dd885a84319b463f8ce4982e0f1f49bc` |

## 概要

AES-CTR のカウンタを任意値に再設定できるサービス。フラグ暗号化時のカウンタ値は禁止されているが、64ビットカウンタを 2^64-1 に設定すると一周して 0 に戻り、フラグと同じ keystream が得られる。

## 解析

server.py は pycryptodome の AES.new(key, MODE_CTR, nonce=8バイト) でフラグを暗号化する。nonce が8バイトなのでカウンタ部は残り8バイト（64ビット）。メニュー2で initial_value を設定できるが、cnt <= (len(FLAG)-1)//16 は拒否される（下限チェックのみ）。pycryptodome の CTR はカウンタが自分の初期値に戻ったときだけ wraparound エラーを出し、2^64-1 → 0 への桁あふれ自体は許す。

## 解法

1. 接続して `encrypted flag` を読む（長さ n）。
2. メニュー2でカウンタを `18446744073709551615` (2^64-1) に設定。
3. メニュー1で `00` を (16+n) バイト暗号化。1ブロック目はカウンタ 2^64-1、2ブロック目以降はカウンタ 0,1,2,... の keystream。
4. 先頭16バイトを捨てた keystream と暗号化フラグを XOR。

```python
send("2"); send(str(2**64-1))
send("1"); send("00"*(16+n))
ks = bytes.fromhex(enc_text)[16:]
flag = bytes(a^b for a,b in zip(enc_flag, ks))
```

ソルバー全体は settable-counter-solver.py（metis remote pipe で共有インスタンスに接続）。

## 使用したスクリプト

- [settable-counter-solver.py](files/settable-cou/settable-counter-solver.py)

## 学び・再利用できる手法

CTR の『使用済みカウンタ禁止』が下限チェックだけなら、カウンタ幅でのラップアラウンドを疑う。nonce 長からカウンタ幅を逆算すること。

- **CTR counter wraparound to reuse a forbidden keystream**（crypto）: When a CTR service forbids re-using the counter values used for a secret only by a lower-bound check, set the counter to the maximum value of the counter field so it overflows back to zero; encrypting known zeros then yields the secret's keystream (skip the blocks before the wrap).
  - 適用条件: Settable CTR initial counter, counter field narrower than the block (e.g. 8-byte nonce + 8-byte counter), library allows wrap except back to its own initial value (pycryptodome).

## METISの記録

- 期間: 2026-11-16 09:04 JST 〜 2026-11-16 09:11 JST
- 使用アクション数: 6（official_flag_submission_browser ×1, read_only_artifact_analysis ×1, remote_service_solver_pipe ×2, sandboxed_dynamic_execution ×2）
- 判定方式: official_browser_observed

### 提出履歴

| 時刻 | 判定 | 回数 |
| --- | --- | --- |
| 2026-11-16 09:11 JST | correct | 1 |

### 仮説の変遷

| 時刻 | 状態 | 仮説 | 根拠 |
| --- | --- | --- | --- |
| 2026-11-16 09:05 JST | proposed | CTR 64bit counter wraparound: set counter 2^64-1, encrypt zeros, keystream blocks after the first equal counters 0..n used for the flag | server.py: nonce 8 bytes, check only cnt <= (len(FLAG)-1)//16; pycryptodome errors only when counter returns to its initial value |

### 配布ファイル・取得データ

| ファイル | サイズ | SHA-256 |
| --- | --- | --- |
| 00-problem.html | 372,188 | `5c8a8aaf356cd5fdede2522c01ab09174a93fa6cde3c28620c9febe9a1174747` |
| 01-00-server.py | 1,209 | `7cef7282b05942bc2378e23785b5c02b837f0ff1ee732d0859e012231c519a92` |
| .metis-remote/9911d2cbbe5d497b973650c42764fe93.recv | 387 | `06c0c02ba58897bafa94af5b9521806923fdcd67fc4d5945758d63119070b56b` |

### 接続先

- 34.170.146.252:26148

<sub>METIS writeup — 更新: 2026-11-16 09:11 JST</sub>
