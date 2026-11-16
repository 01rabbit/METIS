# nested eval (misc/jail, 6.5) — 未解決(blocked): 解法は特定、インスタンス未取得

## 配布物
- chal.py:
  ```python
  code = input("jail> ")
  assert code.isascii()
  prohibited = ["(", ")", "\\", "+", "__"]
  assert not any(p in code for p in prohibited)
  eval(f"eval({code})")
  ```
- Dockerfile: flag は `/flag-<md5>.txt`(ファイル名がランダム) → 読むにはファイル名の列挙(glob/listdir)が必要。socat で TCP:1337。

## 解析
- 入力は `eval(<入力>)` として外側 eval に評価され、その結果(文字列)が内側 eval で再評価される。
- 禁止チェックは入力の生テキストにだけかかる。内側に渡る文字列は式で組み立てられるので、
  f-string の書式指定 `{40:c}` (= chr(40)) で `(` `)` `_` `\` `+` を、禁止文字を直接書かずに生成できる。
- 方針: 外側 eval に「内側で実行したいコード全体を `{N:c}` の連結で作る f-string」を評価させる。
  内側コード例: `print(open(__import__('glob').glob('/flag*')[0]).read())`
  を各文字コードの `{N:c}` に変換した f"..." を送る(ASCII のみ、禁止文字は含まない)。

## 未達の理由
- 問題サーバーは "Spawn Challenge Server" で個別インスタンスを起動する方式で、起動と提出に AlpacaHack
  へのサインインが必要。無人実行のため認証情報・エンドポイントの付与がなく、リモートに到達できなかった。
- flag は未取得・未提出。上記ペイロードをインスタンス起動後に送れば取得できる見込み(未検証)。
