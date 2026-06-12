# ADR-0004: backend 連携は xiaozhi の Protocol 抽象への実装追加で行う

- Status: Accepted
- Date: 2026-06-12
- 関連: ADR-0001, ADR-0003, docs/repository-analysis.md §5b, docs/backend-protocol.md, Issue #2 / #5 / #7

## コンテキスト

Phase 0 調査の結果、AI 会話の本体は外部依存 `xiaozhi-esp32` の `Application` であり、通信層は純粋仮想 6 メソッド + 7 コールバックの薄い `Protocol` 抽象（websocket_protocol / mqtt_protocol が具象）に分離されていることが判明した。`Application` は接続先・認証を一切持たず、クラウド固有処理は `Ota`（api.tenclass.net のアクティベーション / プロビジョニング）にほぼ閉じている。

PC バックエンド連携の実装方式として、Application ごと自前実装に置き換える案と、Protocol 抽象に backend 用実装を追加して Application を温存する案がある。

## 決定

backend 連携は **xiaozhi の `Protocol` 抽象に backend 用 Protocol 実装（WebSocket）を追加**して行い、`Application`（AFE / VAD / WakeWord / AEC / Opus / 状態機械 / 表情連動 / MCP）は温存する。

- 差し替え点は `InitializeProtocol()` の 1 箇所
- `Ota` のクラウドアクティベーションは無効化し、接続先（NVS `websocket` namespace の url / token）は Setup / BLE から設定する経路を新設する
- backend 側は Opus エンコード / デコードと xiaozhi 互換の JSON メッセージ（tts / stt / llm / mcp / listen / abort）を扱う Adapter を実装し、design-spec §11 の API スキーマとの差分は backend 側で吸収する
- **WS メッセージ・音声フォーマット・接続先設定・ターン管理の契約は `docs/backend-protocol.md` で確定した**。スキーマは xiaozhi 既存スキーマを踏襲する（firmware 改変を最小化）。firmware 側 `BackendProtocol`（#5）と backend 側 WS サーバ + ASR（#7）の契約・作業分割・実装順序も同書で定義する

## 検討した選択肢

- A: Protocol 実装追加・Application 温存（採用）
  - メリット: AFE / VAD / WakeWord / AEC / realtime バージイン / Opus / 表情連動 / MCP を無改修で再利用。Phase 5〜8 の工数・リスクを大幅削減。差し替え点が 1 箇所
  - デメリット: xiaozhi のメッセージスキーマに backend 側が合わせる必要がある（Adapter で吸収）
- B: Application を自前実装で全面置き換え
  - メリット: design-spec の API スキーマを直接実装できる
  - デメリット: 音声パイプライン（AFE / WakeWord / Opus / バージイン）を再実装することになり、リスクと工数が大きい。「既存を壊さない」原則に反する

## 理由

実コード調査により Protocol 境界が十分にきれいであることを確認した。動作実績のある音声パイプラインを温存することが、design-spec の非機能要件（安定性・既存機能を壊さない）に最も適合する。

## 影響

- design-spec §11 の Bot 向け API 仕様は「backend 内部の正規 API」とし、firmware との間は xiaozhi 互換メッセージを backend 側 Adapter が変換する構成になる（具体的な対応づけは `docs/backend-protocol.md` §2.3 / §4.3 に確定）
- バージイン（Phase 8）は xiaozhi の `kListeningModeRealtime` + AEC 経路を再利用できる見込み。CoreS3 で AEC を有効化するには xiaozhi の Kconfig `USE_DEVICE_AEC` の depends に StackChan ボードを追加するパッチが必要（実機検証は別途。`docs/backend-protocol.md` §6 / §8 未決事項参照）
- backend に TTS（音声合成）port が存在しないため、下り Opus 音声を返すには TTS port + Opus enc の新設が必要（`docs/backend-protocol.md` §4.3 / §8）
- 本 ADR は Phase 3/5（Issue #5 / #7）に先立つプロトコル設計の確定（`docs/backend-protocol.md`）をもって **Accepted** とする
