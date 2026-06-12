# ADR-0007: backend の OTA チェック応答で xiaozhi 互換 `websocket` セクションを返す

- Status: Accepted
- Date: 2026-06-12
- 関連: Issue #23 / Issue #5 / Issue #7 / ADR-0003 / ADR-0004 / docs/backend-protocol.md §5.3 / docs/backend-api.md §1b

## コンテキスト

firmware（xiaozhi-esp32）の `Application::InitializeProtocol`（`application.cc:473-487`）は、
通信プロトコルを起動時に 1 度だけ選ぶ。選択は `Ota::CheckVersion`（`ota.cc:77-245`）が
HTTP で受け取る OTA チェック応答に依存する:

- 応答に `mqtt` セクションがあれば MQTT（最優先）
- 無く `websocket` セクションがあれば WebSocket
- どちらも無ければ既定で MQTT

`Ota::CheckVersion` は `wifi.ota_url` へ `Board::GetSystemInfoJson` を本体に持つ `POST` を投げる
（ヘッダ `Device-Id`(MAC) / `Client-Id`(UUID) / `User-Agent` / `Content-Type` / `Activation-Version`）。
#5（PR #22, `backend_config.cc`）で `wifi.ota_url` は backend に向く実装が入った。したがって
**backend がこの OTA チェックに xiaozhi 期待形式で応答しなければ、firmware は WebSocket を選べず
backend との WS 接続が成立しない**（#5 で判明）。

ADR-0003/0004 はクラウド activation（api.tenclass.net）の無効化を決めたが、「backend が何を返すか」は
未確定だった。本 ADR でそれを確定する。

## 決定

backend に **OTA チェック / プロビジョニング・エンドポイント `POST /api/ota/check`** を実装し、
**xiaozhi 互換の `websocket` セクションのみを返す**。

```json
{
  "websocket": { "url": "ws://<host>:<port>/api/bot/<device_id>/audio", "token": "", "version": 2 },
  "firmware":  { "version": "<device 現バージョン>" }
}
```

- `websocket` のキーは `url` / `token` / `version`（`websocket_protocol.cc:84-87` が読むキーに厳密一致）。
- **`activation` セクションは返さない** → device はクラウド activation をスキップする（`ota.cc:122-144`）。
- **`mqtt` セクションは返さない** → firmware が MQTT を WebSocket より優先する（`application.cc:480`）のを避ける。
- device は `Device-Id`(MAC) ヘッダで識別し、WS URL の `<device_id>` に用いる。未登録 device は本応答時に
  `RegisterBotUseCase` で登録する（OTA チェックが device の初回接触のため）。
- `firmware.version` は device の現バージョンをそのまま返し `url` を付けない。両方揃って初めて
  `has_new_version_` が立つ（`ota.cc:225-238`）ため、backend がファーム配信をしないことと整合する。
- WS URL のスキーム/ホスト/ポート・`token`・`version` は config（`STACKCHAN_OTA_WS_*`）由来とし、
  ルートにハードコードしない（CLAUDE.md）。

## 検討した選択肢

- A: backend が OTA チェック応答で `websocket` セクションを返す（採用）
  - メリット: firmware 無改修で WebSocket 選択が成立する。device 側の手動 NVS 設定が不要になる。
    xiaozhi の既存 Ota フローをそのまま使うため `Application` を一切触らない（ADR-0004 と整合）。
  - デメリット: backend が xiaozhi の OTA 応答スキーマに合わせる必要がある（薄い変換ルートで吸収）。
- B: OTA 応答を返さず、NVS `websocket` を Setup/BLE からのみ埋める（backend-protocol.md §5.1 単独）
  - メリット: backend にエンドポイント追加が不要。
  - デメリット: `wifi.ota_url` を backend に向けた以上、OTA チェックが成功応答を返さないと
    起動フローが不安定になる。手動プロビジョニングが常に必要で運用が重い。
- C: `Ota` 自体を firmware で改修して OTA チェックを省略する
  - デメリット: firmware（外部依存 xiaozhi）への侵襲。ADR-0004「Application/通信フローを温存」に反する。

## 理由

`Ota::CheckVersion` / `HasWebsocketConfig` / `InitializeProtocol` の実コードを読み、
firmware は「`websocket` セクションの有無」だけで WS を選ぶことを確認した。最小の応答で
firmware 無改修・device 手動設定なしの接続成立が可能で、ADR-0004 の「通信フロー温存」方針に最も適合する。
`activation`/`mqtt` を返さないことが、クラウド activation スキップと WebSocket 確実選択の両方を満たす。

## 影響

- backend に `app/interfaces/api/ota_routes.py`（`POST /api/ota/check`）と config キー
  `STACKCHAN_OTA_WS_{SCHEME,HOST,PORT,PATH_PREFIX,VERSION,TOKEN}` を追加。
- `ota_ws_host` の既定 `127.0.0.1` はデプロイで **必ず** device 到達可能な LAN アドレスに上書きする
  （device は localhost に到達できない）。
- backend-protocol.md §5.3 / backend-api.md §1b に応答契約を確定。§5.1 の Setup/BLE 経路とは併存可で、
  OTA 応答が来れば `Ota` が NVS `websocket` を上書きする（`ota.cc:170-182`）。
- 申し送り（#5/#10）: firmware は `server_time`（時刻同期）も OTA 応答から取り込めるが（`ota.cc:188-211`）、
  本 backend は未対応。時刻同期が必要なら別途 `server_time` セクション追加を検討（現状は接続成立に不要）。
  `token` の発行/検証（device 認証）は現状 config 固定値のみで、デバイス個別トークン管理は未対応。
