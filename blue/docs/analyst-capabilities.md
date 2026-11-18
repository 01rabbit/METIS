# 知識・ツール・実証の区別

元リポジトリには分析用Python実装もあります。ファイル棚卸しで「旧実行系」に分類した
だけでは、METISにその解析機能があることになりません。元実装は直接移植せず、必要な仕様から
独立して限定的な解析CLIを実装しました。[形式・上限・出力仕様](artifact-tools.md)を確認してください。

| 分野 | 維持する分析上の要件 | METISで実行するための条件 |
| --- | --- | --- |
| EML/MBOX、ヘッダー | 信頼できる受信境界、MIME、配信とクリックの区別 | 同梱CLI: ヘッダー・MIMEメタデータとhash。認証の真正性は別途確認 |
| Chromium/Firefox SQLite | 一貫したDB/WAL、スキーマ、epoch、visitとURL、DL完了 | 同梱CLI: 対応テーブルを私有コピーから読取。取得範囲と未対応schemaを明示 |
| EVTX/XML | provider+ID、同一レコード、100ns精度、部分失敗 | 同梱CLI: UTF-8 Event/Events XMLのみ。バイナリEVTXは外部パーサー |
| Prefetch | フォーマット版、圧縮/チェックサム、内部実行時刻 | 対応版を検証した外部ツール |
| Windows各種痕跡 | Amcache/ShimCache/BAM/MFT/USNの意味の違い | 外部ツールの出力と原本再確認 |
| APIモニター記録 | ポインター幅、オフセット、callとbufferの対応 | 対応コンテナーの外部パーサー |
| Windows/Linuxメモリ | 画像・symbols、pluginの範囲、空結果と失敗 | Volatility等、対応symbols、十分なメモリ |
| 静的PE/ELF/Go | 命令境界、VA/RVA/offset、参照と実行の違い | 安全に利用できる逆アセンブラー等 |
| Android | download/indexing/foregroundの区別、権限と実行 | APK・DB等の静的解析ツール |
| Office/PDF | マクロ・埋め込み・外部参照、表示と抽出の差 | 対応コンテナー/文書解析ツール |
| CloudTrail | 母集団、eventID、成功条件、匿名/認証、S3操作 | 同梱CLI: JSONのeventID重複・衝突・主体・結果を区別。収集用クラウドAPIなし |
| クラウドID/Kubernetes | 主体と委任、audit stage、要求と実行結果 | プロバイダー監査データ |
| JSON厳密数値 | Decimal、型、重複キー、同率、完全性 | 同梱CLI: 厳密数値・元表記・同率保持。重複キーや非有限値は拒否 |
| HTTP/PCAP/印刷プロトコル | 双方向再構成、gap/overlap、宣言長、response | tshark等と必要なプロトコル対応 |
| DNS/ネットワークID | PSL、方向、NAT/重複、IPと端末IDの根拠 | 既存pcap/センサーログの解析環境 |
| 宇宙リンク | packet/frame、長さ、sequence、CRCと認証の差 | 当該フォーマットを扱えるオフラインツール |
| アーカイブ/圧縮 | traversal、展開上限、途中失敗、セグメント | 制限と安全な出力先を持つ解凍環境 |
| Git証拠/秘密検出 | checkoutを避ける、object/ref整合性、私有化 | 証拠リポジトリ用の隔離された静的読取 |
| TI | 情報源別first-seen、alias、指標の役割 | 許可された参照先・外部接続 |

METISはこの限定CLIに加え、ワーカープール、状態/ログ、接続管理、読み取りSIEM API、
評価、ナレッジ監査と取り込みゲートを同梱します。上表の外部ツールを一式インストール
する機能や、それらの正しい動作をモデル名だけで保証する機能はありません。

Claude CLIワーカーの標準構成はRead/Glob/Grep/WebFetch/WebSearchで、BashやMCPを
開放していません。したがって、オーナーが承認済みの環境で前処理して抽出結果を渡すか、
必要なツールが使えるネイティブ実行を選ぶ必要があります。モデル名だけで利用可能な
解析機能や権限が増えることはありません。

従来の断定的な説明も修正しました。RC4チケット、LSASSアクセスマスク、privileged
コンテナー、メタデータサービスへの通信、未応答フロー等は、それ単独で攻撃成功や
ホスト侵害を確定させません。収集範囲・正常系・相関証拠を確認して判断します。

今回の[技術棚卸し](technical-retention.md)では、PATH・table/column・イベント・結合キー・
型/単位・解釈限界を対応するskill参照へ補いました。表にある外部ツールの同梱や、新しい
ライブAPIの実装を意味しません。APMXの候補構造だけでは未知の採取物の版を確定できないため、
候補オフセットを一般仕様として使わず、対応版のネイティブ出力との照合を必要条件にします。

仕様の確認先として、メールの認証結果と信頼境界は
[IETF RFC 8601](https://www.rfc-editor.org/info/rfc8601/)、DB本体とWALの関係は
[SQLiteのWAL仕様](https://www.sqlite.org/wal.html)を参照します。本文・実装の転載は行いません。
