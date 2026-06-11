# CoreS3 AI Bot 改修 設計・仕様書

## 1. 目的

M5Stack CoreS3 上で動作する既存 AI ボット OSS（StackChan）を改修し、外部 API 依存型の会話ボットから、**ノート PC 上の AI エージェントバックエンドと連携する拡張可能な AI Bot 端末**へ変更する。

- CoreS3 側は音声入出力・画面表示・カメラ入力・簡易制御を担う **「AI エージェントに身体を与える端末」** として扱う
- LLM・音声認識・画像認識・Wake Word・エージェント制御・設定管理は **PC 側 Python バックエンドに集約** する
- 最終的に HermesAgent / OpenClaw / OpenAI 互換 API / Codex をバックエンドとして選択可能にする

### 一文要約

> CoreS3 を AI 処理本体ではなく、PC 上の AI エージェントに接続する入出力端末として再設計し、AI 処理・モデル管理・Prompt 管理・Wake Word・音声認識・画像認識・設定管理を Python バックエンドと Web ダッシュボードへ集約する。

## 2. 全体アーキテクチャ

```
[CoreS3 AI Bot]
  マイク入力 / スピーカー出力 / カメラ入力 / 表情・画面表示
  Wake Word 検知 / Bot 状態管理 / PC バックエンド通信

        ↓ HTTP / WebSocket

[PC Backend Server / Python]
  Bot 向け API / LLM 互換 API / Agent API
  Speech Recognition API / Vision Recognition API
  Wake Word API / Settings API / Dashboard API

        ↓

[Agent / Model Backend]
  HermesAgent / OpenClaw / OpenAI 互換 API / Codex
  任意 LLM / 任意音声認識モデル / 任意画像認識モデル
```

### 2.1 役割分担

| | CoreS3 側 | PC バックエンド側 |
|---|---|---|
| 責務 | Wi-Fi 接続、バックエンド接続、マイク入力取得・音声送信、スピーカー出力、カメラフレーム取得・送信、画面・表情表示、Wake Word 軽量検知、Bot 状態表示、簡易的な顔・視線制御、既存の画面系設定の維持 | LLM API ラッパー、Agent 連携（HermesAgent / OpenClaw / OpenAI 互換 / Codex）、音声認識、画像認識、Wake Word 設定・モデル管理、Web ダッシュボード、設定永続化、Bot 状態管理、CoreS3 への制御指示、ログ・エラーハンドリング |
| 持たない物 | 複雑な AI 設定・モデル設定 | （CoreS3 固有のハードウェア制御） |

### 2.2 技術選定

**CoreS3 側**: 既存リポジトリの技術スタックを尊重する（Arduino / PlatformIO / ESP-IDF / M5Unified / M5GFX / Wi-Fi / HTTP / WebSocket / I2S / Camera Driver）。Arduino ベースなら ESP-IDF へ全面移行しない。構造のみ整理する。

**PC バックエンド側**: Python を基本とする（ML / AI 系ライブラリが豊富、音声・画像・Wake Word モデルを扱いやすい）。
候補: FastAPI / Pydantic / SQLModel・SQLAlchemy / SQLite / WebSocket / Uvicorn / OpenAI 互換クライアント / faster-whisper・sherpa-onnx / OpenCV / ONNX Runtime / PyTorch

## 3. CoreS3 側 設計

### 3.1 保持する設定（最小限）

- Wi-Fi SSID / Password
- Backend Server URL / Dashboard URL
- Device ID / API Key（Pairing Token）
- 既存の画面・端末系基本設定（明るさ、表情、音量、テーマ、スリープ、デバイス名 等）— **可能な限り維持する**

### 3.2 持たせない設定（バックエンド側で管理）

エージェントタイプ / LLM モデル / Prompt / 音声認識モデル / 画像認識モデル / Wake Word（文字列・有効無効・検知方式・モデル）/ エージェントツール設定 / 会話履歴設定

### 3.3 推奨ディレクトリ構成

```
firmware/src/
  main.cpp
  domain/          bot_state.h / bot_config.h / bot_event.h
  application/     bot_controller.h / voice_interaction_service.h
                   vision_tracking_service.h / wakeword_service.h
  infrastructure/
    hardware/      display_driver.h / microphone_driver.h / speaker_driver.h / camera_driver.h
    network/       backend_client.h / websocket_client.h
    storage/       config_storage.h
  presentation/    face_renderer.h / status_screen.h
```

既存構成に合わせて調整してよいが、以下は守る:
ハードウェア依存・API 通信・設定保存の隔離、Bot 状態管理の分離、画面描画の分離、音声処理と LLM 通信の分離、**既存機能を破壊しない**。

## 4. PC バックエンド 設計

### 4.1 提供 API

音声認識 API / LLM・Agent API / 画像認識 API / Wake Word API / 設定 API / Bot 状態 API / ダッシュボード API / Bot 制御 API

### 4.2 推奨ディレクトリ構成（FastAPI + クリーンアーキテクチャ）

```
backend/app/
  main.py
  domain/         bot / agent / speech / vision / wakeword / settings
                  （各 entities.py / value_objects.py / services.py）
  application/
    use_cases/    process_voice_input / process_agent_request / update_bot_settings
                  update_agent_settings / run_vision_detection / update_wakeword_settings
                  estimate_sound_direction
    ports/        agent_gateway / speech_recognizer / vision_recognizer
                  wakeword_detector / settings_repository / bot_event_publisher
  infrastructure/
    agent/        hermes_agent_gateway / openclaw_gateway / openai_compatible_gateway
    speech/       whisper_recognizer / local_asr_recognizer
    vision/       opencv_face_detector / motion_detector / onnx_vision_recognizer
    wakeword/     local_wakeword_detector
    persistence/  sqlite_settings_repository
    transport/    websocket_bot_event_publisher
  interfaces/
    api/          bot / agent / speech / vision / wakeword / settings の各 routes
    dashboard/    routes / schemas
  di_container/   唯一の具象依存解決ポイント（ports の ABC ↔ infrastructure の具象を結合）
  config/         settings.py
backend/tests/
```

### 4.3 依存方向

```
interfaces → application → domain
infrastructure → application ports → domain
```

Domain は FastAPI / DB / OpenAI SDK / OpenCV 等に依存しない。
Provider 分岐は if 文の増殖ではなく Adapter / Port（`AgentGateway` ├ Hermes / OpenClaw / OpenAICompatible）で差し替え可能にする。

### 4.4 DDD 主要概念

| 概念 | 主な属性 |
|---|---|
| **Bot** | device_id, name, firmware_version, backend_url, connection_status, display/audio/camera_status, current_expression, last_seen_at |
| **AgentProfile** | agent_type (HermesAgent / OpenClaw / OpenAICompatible), model_name, system_prompt, tools_enabled, memory_enabled, temperature, max_tokens, response_mode |
| **SpeechRecognitionConfig** | provider, model_name, language, vad_enabled, noise_reduction_enabled, streaming_enabled |
| **VisionRecognitionConfig** | provider, model_name, face/motion/target_tracking_enabled, frame_interval_ms, resolution, processing_location (device / backend) |
| **WakeWordConfig** | enabled, wake_words[]（各エントリ: id, phrase, model_name, threshold, enabled）, detection_method, processing_location (device / backend) |
| **SoundDirectionConfig** | enabled, method, microphone_type, microphone_count, smoothing_enabled, confidence_threshold, fallback_to_face_tracking |
| **VisionStreamPolicy** | idle_fps, motion_detected_fps, face_detected_fps, tracking_fps, conversation_fps, resolution, jpeg_quality, send_only_on_motion, max_frame_size, processing_location |
| **AttentionDetectionConfig** | enabled, require_face_centered, require_head_pose, require_gaze_estimation, attention_duration_ms, confidence_threshold |
| **ProactiveTalkConfig** | enabled, cooldown_seconds, max_count_per_day, allow_without_wake_word, allow_during_conversation, disabled_in_focus_mode, disabled_at_night |
| **VisionState** | Idle / MotionDetected / FaceDetected / Tracking / AttentionDetected / Conversation |
| **ConversationTurnConfig** | barge_in_enabled, aec_enabled, vad_threshold, vad_threshold_while_speaking, min_interruption_duration_ms, end_of_turn_silence_ms, semantic_end_of_turn_enabled, max_utterance_duration_ms, interrupt_behavior |
| **TurnState** | Idle / UserSpeaking / Thinking / BotSpeaking / Interrupted |

## 5. 画像認識・フレーム送信仕様

### 5.1 基本方針: 適応的フレーム送信

CoreS3 から PC バックエンドへの画像フレーム送信は **常時高頻度では行わない**。
常時送信は Wi-Fi 通信・メモリ・CPU・発熱・電力・音声処理や会話処理への影響が大きいため、**Bot の状態に応じて送信頻度・解像度・処理場所を切り替える**。

| 状態 | 送信頻度目安 | 内容 |
|---|---|---|
| Idle | 0.5〜2 FPS / 低解像度 | CoreS3 側の簡易動体検出（フレーム差分）のみ。PC への送信は停止または低頻度 |
| MotionDetected | 2〜5 FPS / 低〜中解像度 | PC へ送信開始、PC 側で顔検出。顔がなければ Idle へ戻る |
| FaceDetected | 3〜5 FPS | 顔位置・顔向き推定、Bot の視線・表情制御 |
| Tracking | 3〜10 FPS | 顔・動体追跡、視線制御。見失ったら一定時間探索後 Idle へ |
| Conversation | 3〜5 FPS（上限あり） | 顔追跡継続・表情制御・会話終了判定。音声処理を優先する |

### 5.2 処理場所の分担

- **CoreS3 側（軽量のみ）**: フレーム取得、簡易フレーム差分・動体検出、低解像度画像送信、制御指示の反映、表情・視線・状態表示。重い画像認識モデルは原則動かさない
- **PC 側（重い処理）**: 顔検出・顔追跡・動体追跡、顔向き推定、視線推定、注視判定、自発話しかけ判定、モデル切り替え、CoreS3 への制御コマンド生成

## 6. 「目が合ったら話しかける」機能（注視検出・自発話しかけ）

### 6.1 用語整理

| 用語 | 意味 |
|---|---|
| 顔検出 | 画像内に顔が存在するか検出 |
| 顔追跡 | 検出した顔の位置を継続的に追跡 |
| 顔向き推定 | 顔が Bot 方向を向いているか推定 |
| 視線推定 | 目線が Bot 方向を向いているか推定 |
| 注視判定 | 顔向き・視線・継続時間から Bot を見ているか判定 |
| 自発話しかけ | 注視判定が成立した場合に Bot から話しかける |

### 6.2 段階実装方針

- **初期実装**: 厳密な視線推定は行わない。「顔が検出されている ∧ 顔が画面中央付近 ∧ 顔サイズ一定以上 ∧ 正面向きに近い ∧ 一定時間継続」で「Bot を見ている可能性が高い」と判定する
- **発展実装**: PC 側で 顔検出 → 顔ランドマーク → 頭部姿勢推定 → 視線推定 → 注視判定 を導入する。カメラ画質・距離・照明に依存するため拡張機能扱いとし、初期リリースの必須にしない

### 6.3 自発話しかけ条件

以下を **すべて** 満たした場合のみ実行する:

- 自発話しかけ機能が有効
- 注視状態が一定時間継続している
- 直近の自発話しかけから一定時間以上経過している（クールダウン）
- 会話中ではない、または割り込み可能な状態
- 夜間モード / 集中モード / ミュート状態ではない
- バックエンド側が話しかけ可能と判定している

### 6.4 クールダウン制御

- 最短クールダウン: 5 分（設定可能）
- 同一セッション内の最大自発話しかけ回数: 1〜3 回
- ユーザーが無視した場合は次回までの間隔を伸ばす

### 6.5 Bot 状態遷移

```
Idle → MotionDetected → FaceDetected → AttentionDetected → ProactiveTalk → Conversation → Idle
```

- **Idle**: 低頻度監視、Wake Word 待機、動体検出待機、バックエンド接続維持
- **MotionDetected**: PC へ画像送信開始、顔検出試行。顔がなければ Idle へ
- **FaceDetected**: 顔位置追跡・顔向き推定、Bot の視線を合わせる
- **AttentionDetected**: 注視継続時間を計測し、自発話しかけ条件を評価
- **ProactiveTalk**: Agent に自発話しかけ用プロンプト送信 → 返答生成 → 発話 → クールダウン更新
- **Conversation**: 音声認識・Agent 応答・顔追跡・表情制御・会話終了判定

## 7. 会話ターン管理・バージイン仕様

### 7.1 目的

Bot（エージェント）の発話中にユーザーが話し始めても、自然に会話を継続できるようにする（バージイン = 割り込み発話対応）。「話す → 聞く」の固定的な交互ターンではなく、会話状態を明示的に管理して自然なターンテイキングを実現する。

### 7.2 技術的課題

- CoreS3 はスピーカー出力中、マイクが自身の再生音を拾う（エコー）。バージインには **AEC（音響エコーキャンセル）が実質必須**
- ESP32-S3 では ESP-SR の AFE（AEC / VAD / ノイズ抑制）が利用可能か、既存ファームウェアとの両立可否を **Phase 0 で調査する**
- AEC が不十分な場合の代替策: Bot 発話中は VAD 閾値を引き上げる、最低割り込み継続時間を長めに設定する、PC 側で再生中の TTS 音声との相関を除去する

### 7.3 会話ターン状態（TurnState）

| 状態 | 内容 |
|---|---|
| Idle | 待機。Wake Word / 注視検出待ち |
| UserSpeaking | ユーザー発話中（VAD 検知中）。音声をストリーミング送信 |
| Thinking | 認識・Agent 処理中 |
| BotSpeaking | Bot 発話中。**マイク入力と VAD を継続し、バージインを監視** |
| Interrupted | バージイン検知。TTS 停止処理中 → UserSpeaking へ |

```
Idle → UserSpeaking → Thinking → BotSpeaking → Idle
         ↑                          │
         └──── Interrupted ←────────┘ （バージイン）
```

### 7.4 バージイン処理フロー

1. BotSpeaking 中もマイク入力を継続取得する（AEC 適用後の信号で VAD）
2. 一定時間以上（例: 300〜500ms、設定可能）の連続発話を検知したらバージイン候補とする
3. 誤検知防止のため、Bot 発話中は通常より高い VAD 閾値・長い最低継続時間を適用する
4. バージイン確定で TTS 再生を停止（即停止 / フェードアウト / 文末まで、設定で選択）し、UserSpeaking へ遷移する
5. 発話の中断位置を記録し、Agent に「発話が中断された」コンテキストを渡す（言い直し・続きの再開判断に利用）

### 7.5 ターン終了判定（End of Turn）

- **一次判定**: CoreS3 側 VAD の無音継続時間（例: 600〜1000ms、設定可能）
- **二次判定（拡張）**: PC 側でストリーミング認識の途中結果から意味的な発話終了を推定する（言いよどみや接続詞で終わっている場合は待つ）。初期リリースの必須にはしない
- 設定項目: 無音閾値時間、最大発話長、セマンティック終了判定の有効 / 無効

### 7.6 通信方式

バージインとストリーミング認識を成立させるため、音声のやり取りは HTTP 単発 POST ではなく **WebSocket 双方向ストリーミングを基本**とする。

- 上り: マイク音声チャンク（Bot 発話中も継続送信）
- 下り: TTS 音声チャンク、制御イベント（`stop_speaking` 等）、部分認識結果、ターンイベント

## 8. Wake Word 仕様

### 8.1 複数 Wake Word 対応

Wake Word は **複数登録できる**ものとして設計する。

- Wake Word ごとに phrase / モデル / 閾値 / 有効・無効を個別に設定できる
- いずれかの Wake Word にマッチしたら起動する
- マッチした Wake Word を Agent のコンテキストに渡せるようにする（呼び名によって応答や人格を変える等の拡張余地）
- CoreS3 側検知の場合、同時に有効化できる個数はメモリ・モデル制約に依存するため上限を設ける（上限超過分は PC 側検知へ委譲、または無効化）

### 8.2 機能

- Wake Word の追加 / 削除 / 変更
- 全体および個別の有効・無効
- 検知方式変更 / モデル差し替え / 閾値変更（Wake Word 単位）

### 8.3 処理場所

- **CoreS3 側検知**: 低遅延・常時音声送信不要・ネットワーク非依存。ただしモデルサイズ・精度・差し替え性・同時登録数に制約
- **PC 側検知**: モデル自由度・精度・差し替え性が高く、複数 Wake Word も扱いやすい。ただし常時音声送信・ネットワーク負荷・遅延・プライバシー設計が必要
- **推奨**: 初期は既存方式を維持し、将来 PC 側検知を追加できる抽象化を入れる

## 9. 発話方向推定仕様

- 発話方向推定は可能だが、内蔵マイクが単一の場合は精度が出ない。**初期実装では必須機能にしない**（音声認識・Agent 応答・顔検出・顔追跡・動体追跡を優先）
- 拡張実装で外付けマイクアレイ構成に対応。方式候補: TDOA / GCC-PHAT / Beamforming / DOA 推定
- 役割分担: **音声方向推定 = 初動、顔検出 = 確認、顔追跡 = 継続**

```
音声検出 → 発話方向推定 → Bot がその方向を見る → 顔検出 → 視線補正 → 会話中は顔追跡を継続
```

## 10. ダッシュボード仕様

PC / スマホのブラウザから Bot の AI 設定を変更する。**プライベートネットワーク内での利用を前提**とする。

| カテゴリ | 設定項目 |
|---|---|
| Bot 基本 | Bot 一覧・接続状態、Backend URL 確認、デバイス情報、FW バージョン、画面系基本設定表示 |
| エージェント | タイプ（HermesAgent / OpenClaw / OpenAI 互換）、モデル、Agent / System Prompt、温度、最大トークン、ツール利用、会話履歴 |
| 音声認識 | モデル・Provider・言語、VAD、ノイズ除去、ストリーミング認識 |
| 会話ターン | バージイン有効・無効、AEC 有効・無効、VAD 閾値（通常 / Bot 発話中）、割り込み最低継続時間、ターン終了無音時間、セマンティック終了判定、割り込み時動作（即停止 / フェードアウト / 文末まで） |
| 画像認識 | モデル、顔検出 / 顔追跡 / 動体検出の有効・無効、処理場所（CoreS3 / PC）、フレーム送信間隔、解像度 |
| 画像送信 | Idle 時送信の有効・無効、状態別 FPS（Idle / Tracking / Conversation）、解像度、処理場所、動体・顔検出トリガー |
| Wake Word | 複数 Wake Word の追加・削除・一覧、全体の有効・無効、Wake Word ごとの有効・無効・閾値・モデル、検知方式、CoreS3 側 / PC 側検知の切り替え |
| 自発話しかけ | 有効・無効、話しかけ条件（顔検出のみ / 中央付近 / 顔向き / 視線）、注視継続時間、クールダウン、1 日あたり最大回数、会話中の割り込み可否、夜間・集中モード無効化、Wake Word なし自発話しかけ許可 |
| 発話方向推定 | 有効・無効、マイク構成、推定方式、顔追跡との併用、信頼度閾値 |

## 11. API 仕様案

### 11.1 Bot 登録 — `POST /api/bot/register`

```jsonc
// Request
{
  "device_id": "cores3-001",
  "firmware_version": "0.1.0",
  "capabilities": {
    "microphone": true, "speaker": true, "camera": true,
    "display": true, "touch": true, "wake_word": true
  }
}
// Response
{
  "bot_id": "cores3-001",
  "settings": { "audio": {}, "display": {}, "wake_word": {}, "vision": {} }
}
```

### 11.2 音声認識 — `POST /api/speech/recognize`

Request: `audio/wav` / `audio/pcm` / `multipart/form-data`

```json
{ "text": "こんにちは", "language": "ja", "confidence": 0.92 }
```

### 11.3 エージェント実行 — `POST /api/agent/chat`

```jsonc
// Request
{
  "device_id": "cores3-001",
  "message": "こんにちは",
  "context": { "wake_word_triggered": true }
}
// Response
{
  "text": "こんにちは、今日は何をしますか？",
  "emotion": "happy",
  "actions": [{ "type": "set_expression", "value": "happy" }]
}
```

### 11.4 画像認識 — `POST /api/vision/detect`

Request: `image/jpeg` / `image/raw` / `multipart/form-data`

```json
{
  "detections": [
    { "type": "face", "bbox": { "x": 120, "y": 80, "width": 64, "height": 64 }, "confidence": 0.88 }
  ],
  "tracking_target": { "x": 152, "y": 112 }
}
```

### 11.5 Bot 制御コマンド取得 — `GET /api/bot/{device_id}/commands`

```json
{
  "commands": [
    { "type": "look_at", "target": { "x": 120, "y": 80 }, "confidence": 0.86 },
    { "type": "set_expression", "value": "thinking" }
  ]
}
```

制御コマンド一覧:

| type | 用途 | 例 |
|---|---|---|
| `look_at` | 顔・動体の方向を見る | `{ "type": "look_at", "target": { "x": 120, "y": 80 }, "confidence": 0.86 }` |
| `set_expression` | 表情変更 | `{ "type": "set_expression", "value": "curious" }` |
| `proactive_speak` | 自発話しかけ | `{ "type": "proactive_speak", "reason": "attention_detected", "text": "なにか手伝おうか？" }` |
| `start_tracking` | 顔追跡開始 | `{ "type": "start_tracking", "target_type": "face" }` |
| `stop_tracking` | 顔追跡停止 | `{ "type": "stop_tracking", "reason": "target_lost" }` |

### 11.6 Wake Word 設定取得 — `GET /api/bot/{device_id}/wakeword`

```json
{
  "enabled": true,
  "detection_method": "local",
  "wake_words": [
    { "id": "ww-1", "phrase": "hello bot", "model_name": "default", "threshold": 0.7, "enabled": true },
    { "id": "ww-2", "phrase": "ねえスタックチャン", "model_name": "default", "threshold": 0.65, "enabled": true }
  ]
}
```

CoreS3 側検知の同時有効数には上限を設け、超過分は PC 側検知へ委譲または無効として返す。

### 11.7 自発話しかけ Agent リクエスト

```jsonc
// Request（バックエンド → Agent）
{
  "device_id": "cores3-001",
  "event_type": "attention_detected",
  "context": {
    "face_detected": true,
    "attention_duration_ms": 1800,
    "last_proactive_talk_seconds_ago": 900,
    "conversation_active": false
  }
}
// Response
{
  "text": "なにか手伝おうか？",
  "emotion": "curious",
  "actions": [
    { "type": "set_expression", "value": "curious" },
    { "type": "proactive_speak", "reason": "attention_detected" }
  ]
}
```

### 11.8 音声ストリーミング — `WS /api/bot/{device_id}/audio`

バージイン・ストリーミング認識の基盤となる WebSocket 双方向ストリーミング。

- 上り: マイク音声チャンク（PCM。Bot 発話中も継続送信）
- 下り: TTS 音声チャンク、制御イベント（`stop_speaking` 等）、部分認識結果、ターンイベント（`turn_state_changed` 等）

## 12. 実装ステップ

| Phase | 内容 | 成果物 |
|---|---|---|
| **0: 現状把握** | リポジトリ構造・主要ファイル・ビルド方法・対象ボード・既存 API 連携箇所・設定保存・画面 / 音声 / カメラ / Wake Word 処理の特定、README / docs / 公式ハードウェアリファレンス確認 | `docs/repository-analysis.md`（構成・主要コンポーネント・依存関係・API 連携箇所・設定管理箇所・改修方針・リスク・未確認事項） |
| **1: アーキテクチャ整理** | CoreS3 側の責務分離（§3.3 の構成）。既存コードを壊しすぎない | `docs/architecture.md` |
| **2: PC バックエンド追加** | Bot 登録 API / Settings API / Speech・Agent・Vision API のダミー / Dashboard 最小画面 / SQLite 設定保存 | `backend/`, `docs/backend-api.md` |
| **3: CoreS3 → バックエンド連携** | Backend URL 設定、起動時 Bot 登録、設定取得、音声送信、Agent 呼び出し、応答受信、表情変更コマンド受信、エラー時画面表示 | — |
| **4: LLM / Agent ラッパー** | AgentGateway 抽象 + Hermes / OpenClaw / OpenAICompatible の Adapter（OpenAI 互換を優先） | — |
| **5: 音声認識バックエンド化** | 既存音声認識 API 依存を外し PC 経由に。WebSocket ストリーミング送信、モデル切り替え・ダッシュボード反映 | — |
| **6: 画像認識・追跡** | カメラフレーム取得・送信、顔検出・顔位置返却、表情 / 視線制御、動体検出・追跡 | — |
| **7: Wake Word 設定拡張** | 設定 API / UI、複数 Wake Word 管理、有効・無効、検知方式切り替え、モデル差し替え用設計（初期は既存処理の抽象化まで） | — |
| **8: 会話ターン管理・バージイン** | AEC 利用可否調査（ESP-SR AFE 等、Phase 0 の調査結果を活用）、Bot 発話中の VAD 継続、バージイン検知・TTS 停止、ターン終了判定、中断コンテキストの Agent 連携 | — |

## 13. 非機能要件

### 保守性

- ハードウェア依存・API 依存・モデル依存を閉じ込める
- 設定項目を型で管理する、グローバル変数に直接依存しない
- 巨大な main.cpp に処理を集めない
- Provider 分岐を if 文で増やし続けず、Adapter / Port で差し替え可能にする

### 安定性

- Wi-Fi 切断時に復帰できる
- バックエンド未起動 / API タイムアウト時に落ちない
- 音声認識失敗時に会話ループが壊れない
- バージイン誤検知（エコー・環境音）で Bot 発話が不必要に中断され続けない
- カメラ失敗時に Bot 全体が停止しない
- 設定読み込み失敗時はデフォルト値で起動する

### パフォーマンス

- CoreS3 側で重い AI 推論をしない
- 画像送信は解像度・頻度を状態に応じて制限する（§5）
- 音声送信は必要最小限にする
- WebSocket 利用を検討する
- メモリ使用量・フレームバッファの扱いに常に注意する

### セキュリティ

プライベートネットワーク前提だが、最低限以下を考慮する:
API Key / Pairing Token、ダッシュボード認証、LAN 内の意図しない操作防止、CORS 制限、設定 API の保護、モデル設定・Prompt の保存先保護、**外部公開しない前提の明文化**。

## 14. 優先順位

| 優先度 | 項目 | 理由 |
|---|---|---|
| 高 | 既存リポジトリ把握 | ここを飛ばすと全部壊れる |
| 高 | CoreS3 公式仕様確認 | マイコンは雰囲気実装すると即破綻する |
| 高 | API 依存箇所の特定 | 置き換え対象の中心 |
| 高 | 設定責務の分離 | ダッシュボード化の前提 |
| 高 | PC バックエンド設計 | 今回の中核 |
| 高 | CoreS3 のサーバー URL 設定 | Bot を PC 側へ接続する入口 |
| 中 | Agent ラッパー | HermesAgent / OpenClaw / Codex 連携 |
| 中 | 音声認識モデル切替 | 自由度向上 |
| 中 | 顔検出・顔追跡 | Bot 体験の向上 |
| 中 | Wake Word 設定変更（複数対応含む） | 体験改善 |
| 中 | 会話ターン制御・バージイン | 自然な会話体験の中核。AEC 可否に依存するため調査は早期に行う |
| 低〜中 | 発話方向推定 | マイク構成次第 |
| 低〜中 | Wake Word モデル差し替え | 後続拡張でよい |

## 15. 実装時の指針

### やってはいけないこと

- 現リポジトリを読まずに大規模リファクタする
- M5Stack / CoreS3 の仕様確認なしにカメラ・マイク処理を書く
- main.cpp に全部詰め込む / API URL をハードコードする
- Provider ごとの処理を if 文で直書きし続ける
- 既存の画面設定・表示機能を壊す
- メモリ制約を無視して画像や音声を保持する
- PC 側前提の処理を CoreS3 側に持ち込む
- Wake Word をいきなり全面作り直す
- 動作確認できないハードウェア処理を断定的に実装する
- 常時高頻度の画像フレーム送信を前提にする

### 必ずやること

- README / docs / 公式仕様を読む
- 既存 API 連携箇所・既存設定型を特定する
- 既存ビルドが通る状態を維持し、変更前後でビルド確認する
- 小さい PR 単位で変更する
- 仕様不明な箇所は TODO として明示する
- ハードウェア依存処理は Adapter 化する
