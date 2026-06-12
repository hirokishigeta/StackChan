# backend-protocol: firmware ↔ backend WebSocket 契約仕様（Phase 3/5 設計）

firmware の `BackendProtocol`（xiaozhi `Protocol` 抽象の WebSocket 実装、Issue #5）と
backend WebSocket サーバ（Issue #7）の**契約仕様**。ADR-0004（案 A: Protocol 抽象に
backend 用実装を追加し Application 温存）の確定設計。

- 本書は **実コードに厳密に基づく**。推測は「推測」と明記する。
- 出典: `firmware/xiaozhi-esp32/main/protocols/protocol.h` / `protocol.cc` /
  `websocket_protocol.cc`、`application.cc:480-609`、`docs/repository-analysis.md` §5b、
  `docs/architecture.md` S6、`docs/backend-api.md`、`docs/design-spec.md` §7 / §11。
- 関連 ADR: ADR-0003（クラウド接続削除）、ADR-0004（本設計で Accepted）。

---

## 0. 全体像

```
  ┌──────────────── CoreS3 firmware ────────────────┐        ┌──────────── PC backend (FastAPI) ────────────┐
  │  xiaozhi Application (温存)                       │        │  WS /api/bot/{device_id}/audio               │
  │   AFE/VAD/WakeWord/AEC/Opus/状態機械/表情/MCP      │        │   ├ Opus dec(上り16k) → SpeechRecognizer port │
  │      │ 純粋仮想6 + コールバック7                    │        │   ├ AgentGateway port (chat/proactive)        │
  │   Protocol 抽象                                   │        │   └ TTS → Opus enc(下り24k) → 下り音声フレーム  │
  │      └ BackendProtocol(WS) ◀── infrastructure/network      │   制御JSON: tts/stt/llm/mcp/listen/abort      │
  └──────────────────┬──────────────────────────────┘        └──────────────────┬────────────────────────────┘
                     └───────── WebSocket(xiaozhi互換ハンドシェイク+JSON+Opusバイナリ) ────────┘
```

差し替え点は `Application::InitializeProtocol()`（`application.cc:480-487`）の 1 箇所のみ。
firmware は xiaozhi の WebSocket スキーマをそのまま話し、backend がそのスキーマを実装する。

---

## 1. xiaozhi `Protocol` 抽象（`protocol.h` 実シグネチャ）

`Application` はこの 1 抽象だけに依存する。`BackendProtocol` はこれを継承して実装する
（`docs/architecture.md` S6 / #5）。

### 1.1 派生クラスが実装すべきメソッド

| 種別 | シグネチャ | backend 実装の責務（firmware 側 BackendProtocol が満たす） |
|---|---|---|
| 純粋仮想 | `bool Start()` | 初期化のみ（WS は `OpenAudioChannel` 時に接続。xiaozhi WS は `return true`） |
| 純粋仮想 | `bool OpenAudioChannel()` | NVS `websocket` から url/token/version を読み WS 接続、`hello` 送信、サーバ `hello` 待ち、`OnAudioChannelOpened` 発火 |
| 純粋仮想 | `void CloseAudioChannel(bool send_goodbye=true)` | WS 切断（xiaozhi WS は goodbye 不要、`websocket_.reset()`） |
| 純粋仮想 | `bool IsAudioChannelOpened() const` | 接続中 && !error && !timeout |
| 純粋仮想 | `bool SendAudio(unique_ptr<AudioStreamPacket>)` | Opus フレームをバイナリ送信（§3 のフレーム形式） |
| 純粋仮想(protected) | `bool SendText(const std::string&)` | JSON テキスト送信 |
| 仮想(基底に実装あり) | `void SendWakeWordDetected(const std::string&)` | `protocol.cc:51`: `{session_id,type:listen,state:detect,text:<wake_word>}` |
| 仮想(基底に実装あり) | `void SendStartListening(ListeningMode)` | `protocol.cc:57`: `{session_id,type:listen,state:start,mode:auto\|manual\|realtime}` |
| 仮想(基底に実装あり) | `void SendStopListening()` | `protocol.cc:71`: `{session_id,type:listen,state:stop}` |
| 仮想(基底に実装あり) | `void SendAbortSpeaking(AbortReason)` | `protocol.cc:42`: `{session_id,type:abort[,reason:wake_word_detected]}` |
| 仮想(基底に実装あり) | `void SendMcpMessage(const std::string&)` | `protocol.cc:76`: `{session_id,type:mcp,payload:<json>}` |
| 仮想(基底に実装あり) | `void SetError(const std::string&)` / `bool IsTimeout() const` | 既定実装で十分（timeout 120s, `protocol.cc:81`） |

→ **純粋仮想 6（うち `SendText` は protected）+ 基底実装ありの送信ヘルパ 5**。`BackendProtocol` で
**必ず実装が要るのは 6 メソッド**（`Start`/`OpenAudioChannel`/`CloseAudioChannel`/`IsAudioChannelOpened`/`SendAudio`/`SendText`）。
xiaozhi 互換スキーマを踏襲するなら送信ヘルパ 5 は基底実装をそのまま使える。

### 1.2 コールバック（backend → Application 通知。`protocol.cc:7-33` で登録、計 7）

| コールバック | 発火タイミング | Application 側の用途 |
|---|---|---|
| `OnIncomingAudio(packet)` | 下り Opus フレーム受信時 | デコードキューへ（再生） |
| `OnIncomingJson(root)` | 制御 JSON 受信時 | tts/stt/llm/mcp/system/alert を解釈（§2.2） |
| `OnAudioChannelOpened()` | サーバ hello 受信後 | 会話開始準備 |
| `OnAudioChannelClosed()` | WS 切断時 | Idle 復帰 |
| `OnNetworkError(msg)` | `SetError` 経由 | 画面にエラー表示 |
| `OnConnected()` / `OnDisconnected()` | 接続/切断 | （WS 実装では未使用箇所あり。推測: 状態通知用） |

> 注: `hello` タイプの受信は `WebsocketProtocol::OnData` 内で `ParseServerHello` が処理し、
> `OnIncomingJson` には渡らない（`websocket_protocol.cc:152-159`）。backend はハンドシェイク応答として
> 必ず `hello` を返す必要がある（§4.2）。

---

## 2. WebSocket メッセージ契約

すべての制御 JSON は 1 メッセージに `type` を含む。上り（device→backend）の `listen`/`abort`/`mcp`
には `session_id` も含む（基底実装が付与）。

### 2.1 上り（device → backend）

| メッセージ | JSON（実コード由来） | 出典 |
|---|---|---|
| hello | `{type:"hello", version:<2\|3>, features:{aec?:true, mcp:true}, transport:"websocket", audio_params:{format:"opus", sample_rate:16000, channels:1, frame_duration:60}}` | `websocket_protocol.cc:203-226` |
| listen(start) | `{session_id, type:"listen", state:"start", mode:"auto"\|"manual"\|"realtime"}` | `protocol.cc:57` |
| listen(stop) | `{session_id, type:"listen", state:"stop"}` | `protocol.cc:71` |
| listen(detect) | `{session_id, type:"listen", state:"detect", text:"<wake_word>"}` | `protocol.cc:51` |
| abort | `{session_id, type:"abort"[, reason:"wake_word_detected"]}` | `protocol.cc:42` |
| mcp | `{session_id, type:"mcp", payload:<json>}` | `protocol.cc:76` |
| 音声 | Opus バイナリフレーム（§3） | `websocket_protocol.cc:28-58` |

### 2.2 下り（backend → device、`Application::OnIncomingJson` が解釈、`application.cc:521-607`）

| type | フィールド | Application の挙動 | design-spec 対応 |
|---|---|---|---|
| tts | `state:"start"` | Speaking へ遷移 | — |
| tts | `state:"stop"` | Speaking→Listening/Idle | §7.4 `stop_speaking` 相当 |
| tts | `state:"sentence_start", text` | `SetChatMessage("assistant", text)` | — |
| stt | `text` | `SetChatMessage("user", text)`（部分/確定認識結果） | §11.2 認識結果 |
| llm | `emotion` | `SetEmotion(emotion)` — **表情連動の入口** | §11.3 `set_expression` |
| mcp | `payload`(object) | `McpServer::ParseMessage()`（デバイス制御 RPC） | §11.5 制御コマンド |
| system | `command:"reboot"` | `Reboot()` | — |
| alert | `status, message, emotion` | `Alert()` | — |
| custom | `payload` | `CONFIG_RECEIVE_CUSTOM_MESSAGE` 時のみ表示 | — |
| 音声 | Opus バイナリフレーム（下り、§3） | デコード→再生 | §11.8 TTS チャンク |

### 2.3 スキーマ方針: xiaozhi 踏襲 vs design-spec §11 独自 — **推奨: xiaozhi 踏襲**

| 観点 | A: xiaozhi 既存スキーマ踏襲（推奨） | B: design-spec §11 独自スキーマに寄せる |
|---|---|---|
| firmware 改変 | **ほぼゼロ**。送信ヘルパ 5 は基底実装、受信は Application 既存パスをそのまま使う | `Application` の `OnIncomingJson` 分岐や送信ヘルパを改変 → 「既存を壊さない」原則に反する |
| backend 実装 | xiaozhi の tts/stt/llm/mcp/listen/abort を話す Adapter を実装 | §11 の text/emotion/actions を直接実装できる |
| design-spec 整合 | backend 内部の正規 API（§11）と WS 表現の差分を backend Adapter が吸収（ADR-0004「影響」） | WS と内部 API が一致 |
| リスク | 低（動作実績ある音声パイプライン温存） | 高（firmware の状態機械・表情連動・MCP に手を入れる） |

**推奨 = A（xiaozhi 踏襲）**。理由:
1. ADR-0004 の決定（Application 温存、差し替え点 1 箇所）と一貫。
2. `llm.emotion`→`set_expression`、`mcp`→§11.5 制御コマンド、`stt`/`tts.sentence_start`→認識/発話テキストと
   1:1 対応がつき（`repository-analysis.md` §5b.4 の示唆）、backend 側 Adapter で吸収可能。
3. design-spec §11 の REST API（chat/proactive/settings）は backend **内部**の正規 API として維持し、
   WS ループはそれらを ports 経由で呼ぶ（§5）。WS のワイヤ表現が xiaozhi 形でも内部設計は §11 を保てる。

---

## 3. 音声フォーマット契約

| 方向 | フォーマット | 値 | 出典 |
|---|---|---|---|
| 上り（device→backend） | Opus / mono / フレーム | **16000 Hz, 1ch, 60ms** | hello `audio_params`（`websocket_protocol.cc:217-219`）/ `repository-analysis.md` §5b.2 |
| 下り（backend→device） | Opus / フレーム | **既定 24000 Hz, 60ms**（サーバ hello でネゴ） | `protocol.h:86-87` `server_sample_rate_=24000`, `server_frame_duration_=60` |

下りのレートは backend がサーバ hello の `audio_params.sample_rate`/`frame_duration` で指定する
（device は `ParseServerHello` で受領、`websocket_protocol.cc:241-251`）。24k 以外も可だが、device の
スピーカ系と整合する値を返すこと（実機検証要、§7）。

### 3.1 バイナリフレーム形式（version で 3 通り。`protocol.h:17-31`, `websocket_protocol.cc:28-58/112-147`）

- **version 2** = `BinaryProtocol2`（packed, ネットワークバイトオーダ）:
  `version(u16) | type(u16, 0=OPUS) | reserved(u32) | timestamp(u32, server-side AEC 用) | payload_size(u32) | payload[]`
- **version 3** = `BinaryProtocol3`（packed）:
  `type(u8, 0=OPUS) | reserved(u8) | payload_size(u16) | payload[]`
- **その他（version 未設定/0）**: 生 Opus（ヘッダなし）

backend は device の hello `version` に合わせて同じ形式で送受信する。**version 2 は timestamp を持つ
（サーバ側 AEC 用）**。AEC をサーバ側でやる場合は version 2 + timestamp の往復が必要（§6 バージイン参照）。

### 3.2 backend 側で必要な Opus enc/dec

- 上り: Opus(16k/mono/60ms) **デコード** → PCM → SpeechRecognizer port へ。
- 下り: TTS 48k PCM → **48k→24k リサンプル** → Opus(24k/60ms) **エンコード** → バイナリフレーム化（#7-b 実装済み）。
- 実装（#7-a/#7-b）: `opuslib`（libopus バインディング）を採用。`AudioDecoder` / `AudioEncoder`
  port + `infrastructure/audio` 具象（`opus` / `raw`）で registry 解決。native dep は optional
  extra `[opus]` + 遅延ロード。リサンプルは依存なしの線形補間（`infrastructure/audio/resample.py`）。

---

## 4. backend 側の新エンドポイント設計

### 4.1 `WS /api/bot/{device_id}/audio`（design-spec §11.8）を xiaozhi 互換で実装

design-spec §11.8 のパスを採用しつつ、ワイヤプロトコルは §2/§3 の xiaozhi 互換とする。
device 側は NVS `websocket.url` にこのフルパスを設定する（§5.1 で device_id をどう載せるかは未決、§7）。

接続シーケンス（device 視点。`websocket_protocol.cc:83-201`）:

```
device                                  backend (WS /api/bot/{device_id}/audio)
  │── WS Connect (+ HTTP headers) ──────▶│  Authorization: Bearer <token>
  │   Authorization/Protocol-Version/    │  Protocol-Version / Device-Id(MAC) / Client-Id(UUID)
  │   Device-Id / Client-Id              │
  │── {type:hello, audio_params...} ────▶│  上り音声params(opus/16k/1ch/60ms)を受領
  │◀──── {type:hello, transport:        │  session_id 採番 + 下り audio_params(24k/60ms) を返す
  │       "websocket", session_id,       │  （10秒以内。未達なら device 側 SERVER_TIMEOUT）
  │       audio_params}                  │
  │── listen(start, mode) ──────────────▶│  ターン開始（§6）
  │── Opus フレーム × N ─────────────────▶│  → Opus dec → ASR(stream)
  │◀── stt{text} / llm{emotion} / tts ───│  認識結果・表情・発話開始
  │◀── Opus フレーム × N ─────────────────│  TTS 音声
```

### 4.2 サーバ hello（backend が必ず返す）

`{type:"hello", transport:"websocket", session_id:"<採番>", audio_params:{sample_rate:24000, frame_duration:60}}`
（`ParseServerHello` が `transport=="websocket"` を必須チェック、`session_id`/`audio_params` を読む。
`websocket_protocol.cc:228-254`）。

### 4.3 既存 ports / 将来 SpeechRecognizer の WS ループへの接続（クリーンアーキ準拠）

backend の WS ハンドラは `interfaces/`（プレゼンテーション層）に置き、**application/ports 経由でのみ**
インフラを呼ぶ（CLAUDE.md レイヤー依存ルール）。

| WS ループの処理 | 呼ぶ port（ABC） | 既存/新規 |
|---|---|---|
| 上り Opus → PCM → 認識 | `SpeechRecognizer`（`application/ports/speech_recognizer.py`） | 既存 ABC、実装は #7 で faster-whisper 等（現状 `DummySpeechRecognizer`） |
| 認識テキスト → 応答生成 | `AgentGateway.chat(...)`（`agent_gateway.py`） | 既存・実動（OpenAICompatible） |
| device イベント → 自発話 | `AgentGateway.proactive(...)` | 既存 |
| 下り制御イベント配信 | `BotEventPublisher`（`bot_event_publisher.py`） | 既存（現状ポーリング、WS 化は #8） |
| TTS 合成 | `SpeechSynthesizer`（`application/ports/speech_synthesizer.py`） | **新設済み（#7-b）**。具象は Irodori-TTS（ADR-0006）。dummy 既定 |
| 下り Opus enc | `AudioEncoder`（`application/ports/audio_encoder.py`） | **新設済み（#7-b）**。具象は `opus`/`raw`、raw 既定 |

> #7-b で **TTS（音声合成）port `SpeechSynthesizer` と 下り `AudioEncoder` port を新設**した。
> 具象 TTS は Irodori-TTS（`infrastructure/tts/irodori_tts_synthesizer.py`、ADR-0006）で、heavy dep
> （PyTorch / HF チェックポイント）は optional extra `[tts]` + 遅延ロード。既定 provider は `dummy`
> （no-model 環境で `make check` が通る）。`emotion` は絵文字スタイルへマッピング
> （`infrastructure/tts/emotion_style.py`）。Opus enc/dec・リサンプルは `infrastructure/audio` の具象に
> 閉じ込め、WS ハンドラからは port 経由で扱う。未設定/未インストール時は**テキストのみ**にフォールバックし
> 接続を壊さない（design-spec §13）。

WS ハンドラ（DI で各 port を注入）の擬似フロー:
```
on connect    → handshake(hello 交換), session 登録
on listen.start → turn = UserSpeaking
on 上りOpus  → opus_dec → asr.feed() → 部分結果を stt{text} で返す
on listen.stop / VAD終了 → asr.final() → agent.chat() → llm{emotion}+tts{start}+tts{sentence_start}
                           → synth(text,emotion)→48k→24kリサンプル→Opus enc→下りバイナリフレーム列 → tts{stop}
                           （synth/enc が未設定/失敗時はテキストのみへフォールバック, design-spec §13）
on abort      → 進行中 TTS を停止（バージイン、§6）
```

---

## 5. 接続先設定（NVS `websocket` namespace）と Ota 無効化

### 5.1 接続先の設定経路

`WebsocketProtocol::OpenAudioChannel`（`websocket_protocol.cc:84-90`）は NVS namespace **`websocket`** の
`url` / `token` / `version` を読むだけ。クラウド時代はこれを `Ota` が `api.tenclass.net` のプロビジョニング
応答から書き込んでいた（`repository-analysis.md` §5b.5, `ota.cc:146-172`）。

backend 連携では `Ota` 経由をやめ、**Setup/BLE 経路で NVS `websocket` を直接埋める**:
- `url` = `ws://<PC backend host>:<port>/api/bot/{device_id}/audio`（design-spec §11.8）
- `token` = Pairing Token（任意。空なら Authorization ヘッダ無し。`websocket_protocol.cc:101-107`）
- `version` = 2 or 3（推奨は 2: server-side AEC 用 timestamp を持てる。未決、§7）

具体経路は `docs/architecture.md` §6.3-C の「BLE Wi-Fi 設定拡張」に backend URL/token 入力を追加する想定
（#3 の作業。本書はその受け口が NVS `websocket` であることを確定）。

> device_id とパス: design-spec §11.8 は `{device_id}` をパスに含む。一方 device は HTTP ヘッダ
> `Device-Id`(MAC) も送る。backend は **ヘッダ `Device-Id` を正とし、パスの device_id は表示/ルーティング用**
> とするか、両者一致を要求するか未決（§7）。

### 5.2 Ota クラウド activation の無効化（ADR-0003/0004 で繰延べた分）

- `CheckNewVersion` / `ActivationTask`（`application.cc:323-471`）が `Ota::Activate()` を叩く経路を無効化する。
- 既存パッチで `ShowActivationCode()` の音声読み上げは無効化済み（`repository-analysis.md` §5b.5）。
- 残作業（#3 で実施）: activation 必須化を外し、起動時に直接 `OpenAudioChannel`（NVS `websocket`）へ進めるようにする。
  具体的な無効化方法（Kconfig / パッチ / 起動フロー分岐）は #3 の実装で確定（本書は方針のみ）。

---

## 6. ターン管理/バージイン（design-spec §7）と xiaozhi listen mode の対応

xiaozhi は listen mode（`protocol.h:38-42`）と AEC で全二重バージインを既に持つ
（`repository-analysis.md` §5b.6, `application.cc:953/1081`）。

| design-spec §7 TurnState | xiaozhi 対応 | backend がやること |
|---|---|---|
| Idle | `kDeviceStateIdle` | — |
| UserSpeaking | `listen(start)` → 上り Opus 送信 | ASR にフィード、部分結果を `stt` で返す |
| Thinking | listen 停止 / VAD 終了後 | `agent.chat()` 実行 |
| BotSpeaking | `tts{start}` → 下り Opus。**realtime mode なら録音継続** | TTS 配信。上り Opus を監視し続ける |
| Interrupted（バージイン） | device が `abort` 送信 or backend が `tts{stop}` | 進行中 TTS 停止、UserSpeaking へ |

listen mode 対応:
- `kListeningModeAutoStop`: device VAD の無音で自動停止（§7.5 一次判定）。AEC 無効時の既定。
- `kListeningModeManualStop`: 手動停止。
- `kListeningModeRealtime`: **AEC 必須の全二重**。Bot 発話中も録音継続＝バージイン（§7.4）。
  `Application::GetDefaultListeningMode()` が AEC 有効時にこれを選ぶ。

バージインの実現:
- device 側 AEC（`kListeningModeRealtime`）で BotSpeaking 中も上り Opus が来る → backend が VAD/割り込み判定 →
  `tts{stop}` を返して TTS を止める（design-spec §7.4 の `stop_speaking` = xiaozhi `tts.stop`）。
- または device が WakeWord 再検知で `abort(reason:wake_word_detected)` を送る（`protocol.cc:42`）。
- CoreS3 で AEC 有効化には xiaozhi Kconfig `USE_DEVICE_AEC` の depends に StackChan ボードを追加するパッチが必要
  （ADR-0004「影響」、実機検証は別途 = §7 未決）。version 2 フレームの timestamp はサーバ側 AEC 用。

---

## 7. #5 / #7 の作業分割・実装順序・相互依存

### 7.1 作業分割

| Issue | 範囲 | 主な成果物 |
|---|---|---|
| **#3（前提）** | Ota activation 無効化、NVS `websocket` を Setup/BLE から埋める経路（§5） | 起動→`OpenAudioChannel` 直行、URL/token 設定 UI |
| **#5（firmware）** | `BackendProtocol`（infrastructure/network）= `Protocol` 実装。`InitializeProtocol` 差し込み | `network/backend_protocol.{h,cc}`、差し替え点 1 箇所 |
| **#7（backend）** | `WS /api/bot/{device_id}/audio` サーバ + ASR 実装 + Opus dec/(enc) + TTS port | WS ハンドラ、`SpeechRecognizer` 具象、（TTS port 新設） |

### 7.2 実装順序と相互依存

```
#3 (Ota無効化 + NVS websocket 設定経路)         ← 前提。これが無いと #5 は接続先を持てない
        │
        ▼
#7-a (backend WS: hello/handshake + Opus dec + ASR + stt/llm/tts JSON)   ← #5 のテスト相手として先行
        │  (xiaozhi スキーマ §2/§3 が両者の契約 = 本書)
        ▼
#5  (BackendProtocol → InitializeProtocol 差し込み → backend へ接続)
        │
        ▼
#7-b (TTS port + 下り Opus enc)  ← 双方向音声完成。実機で接続/音声検証(§7 未決)
```

- **契約先行**: 本書の §2/§3 スキーマが #5/#7 双方の唯一の契約。これを固定すれば #5 と #7 は並行可能。
- **依存**: #5 は #3（接続先 NVS）に依存。#7-a は契約のみに依存（device 実機なしでもダミー WS クライアントで検証可）。
- **推奨順**: #3 → #7-a（backend WS + 上り ASR、xiaozhi スキーマ準拠の最小サーバ）→ #5（firmware 接続）→ #7-b（TTS/下り音声）。
  上り（認識）と下り（TTS）を分けることで、Phase 5 の主眼（音声認識バックエンド化）を先に成立させられる。

---

## 8. 未決事項（実装前にユーザー判断が必要）

1. **LLM/エージェント provider と接続先**: 既定は OpenAICompatible（`STACKCHAN_AGENT_BASE_URL` 既定
   `http://localhost:11434/v1`、`backend-api.md` §8）。本番で使う provider と base_url/model/api_key を確定する。
   （Anthropic Claude を使う場合は OpenAI 互換ではないため別 Adapter or 互換ゲートウェイの要否を判断）
2. **ASR provider**: faster-whisper / sherpa-onnx 等のいずれか（`backend-api.md` §4.1 TODO issue#7）。
   ストリーミング対応・日本語精度・PC リソースで選定。
3. ~~**TTS provider と下り音声 port の新設**~~: **決定済み（ADR-0006 / #7-b）**。`SpeechSynthesizer` port +
   下り `AudioEncoder` port を新設し、具象 TTS は Irodori-TTS（heavy dep は optional extra `[tts]` + 遅延ロード、
   既定 provider は dummy）。emotion→絵文字スタイル制御、48k→24k リサンプル → Opus enc → バイナリフレーム送出。
   残課題: 参照 wav / モデルチェックポイントの選定、実機でのレイテンシ・読み精度検証（§7 実機検証）。
4. **スキーマ方針の最終承認**: §2.3 推奨 = **xiaozhi 踏襲（案 A）**。これで確定してよいか。
5. **WS バイナリ version**: 2（timestamp 付き・server-side AEC 可）か 3（軽量）か（§3.1）。
6. **device_id とパス/ヘッダの整合**: パスの `{device_id}` とヘッダ `Device-Id`(MAC) のどちらを正にするか（§5.1）。
7. **実機テストの要否**: WS 接続・Opus 往復・AEC/バージイン・下りサンプルレート整合は**実機(CoreS3)でしか
   検証できない**。`USE_DEVICE_AEC` の depends パッチ（§6）も含め、実機検証フェーズを設けるか判断（CLAUDE.md:
   動作確認できないハード処理は断定実装しない／ビルド未確認は明示）。
