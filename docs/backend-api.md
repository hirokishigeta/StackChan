# backend API 仕様（Phase 2 成果物）

PC バックエンド（`backend/`、FastAPI）が LAN 内で提供する API の仕様書。
本書は **実装コード（`backend/app/`）に厳密に一致** させて記述する。設計の正は
`docs/design-spec.md` §11 だが、実装が先行・乖離している箇所は本書末尾の
「design-spec §11 との差分」に明記する。

- ベース実装: `backend/app/main.py`（`create_app()` アプリケーションファクトリ）
- API スキーマ: `backend/app/interfaces/api/schemas.py`
- ダッシュボード: `backend/app/interfaces/dashboard/`
- 設定: `backend/app/config/settings.py`
- AgentGateway 解決: `backend/app/infrastructure/agent/registry.py` + `backend/app/di_container/`

現フェーズは Speech / Vision / WakeWord / Agent(Hermes・OpenClaw) がダミー実装。
実動するのは Bot 登録・設定永続化（SQLite）・コマンドポーリング・Dashboard、および
`OpenAICompatible` を選んだ場合の Agent 実行（OpenAI 互換 HTTP）。

---

## 0. 全体構成

| 項目 | 値 | 出典 |
|---|---|---|
| フレームワーク | FastAPI（`title` = 設定 `app_name`、`version` = `0.1.0`） | `main.py` |
| CORS | `allow_origins` = 設定 `cors_allow_origins`（既定 `["*"]`）、credentials/methods/headers 許可 | `main.py` |
| ルータ | `bot` / `agent` / `speech` / `vision` / `settings` / `dashboard` + `/health` | `main.py` |
| 認証 | なし（プライベートネットワーク前提。design-spec §13） | 実装に認証なし |
| OpenAPI | `/docs`・`/openapi.json`（FastAPI 既定） | FastAPI 既定 |

---

## 1. エンドポイント一覧

| メソッド | パス | tags | 実動 / ダミー | 概要 |
|---|---|---|---|---|
| POST | `/api/bot/register` | bot | 実動 | Bot 登録・設定返却 |
| GET | `/api/bot/{device_id}/commands` | bot | 実動（ポーリング） | 制御コマンドの取得＋キュー消去 |
| GET | `/api/bot/{device_id}/wakeword` | bot | 実動（設定）/ 検知はダミー | 有効 Wake Word 設定の取得 |
| POST | `/api/agent/chat` | agent | OpenAICompatible のみ実動 / 他はダミー | エージェント 1 ターン |
| POST | `/api/agent/proactive` | agent | OpenAICompatible のみ実動 / 他はダミー | 自発話しかけ生成 |
| POST | `/api/speech/recognize` | speech | ダミー（TODO issue#7） | 音声認識 |
| POST | `/api/vision/detect` | vision | ダミー（TODO issue#6/#8） | 画像認識 |
| GET | `/api/settings/{device_id}` | settings | 実動 | 設定集約の取得 |
| PUT | `/api/settings/{device_id}` | settings | 実動 | 設定集約の部分更新（マージ） |
| GET | `/` , `/dashboard` | dashboard | 実動（最小） | Bot 一覧 HTML |
| GET | `/health` | health | 実動 | ヘルスチェック |

「実動 / ダミー」の根拠は §6（実動/ダミーの内訳）を参照。

---

## 2. Bot ルート（`backend/app/interfaces/api/bot_routes.py`）

### 2.1 `POST /api/bot/register`（design-spec §11.1）

Bot を登録し、その設定集約を返す。既存設定があればそれを、無ければデフォルトを保存して返す。

Request（`BotRegisterRequest`）:

```jsonc
{
  "device_id": "cores3-001",       // 必須
  "firmware_version": "0.1.0",     // 必須
  "capabilities": {                 // 任意。省略時は全 true
    "microphone": true, "speaker": true, "camera": true,
    "display": true, "touch": true, "wake_word": true
  }
}
```

Response 200（`BotRegisterResponse`）:

```jsonc
{
  "bot_id": "cores3-001",          // = request.device_id
  "settings": { /* 設定集約。§5 のスキーマ */ }
}
```

- 注意: `bot_id` は `device_id` をそのまま返す（`bot_routes.py`）。
- 注意: `capabilities` はリクエストで受理するが、登録ユースケース
  （`register_bot.py` / `domain/bot/services.py`）では現状保存・反映していない。

ステータス: 200（成功）/ 422（バリデーション）

### 2.2 `GET /api/bot/{device_id}/commands`（design-spec §11.5）

キューに溜まった制御コマンドを返し、同時にキューを空にする（drain）。配信は
WebSocket ではなく **ポーリング**（`InMemoryBotEventPublisher`）。

Response 200（`BotCommandsResponse`）:

```jsonc
{ "commands": [ { "type": "set_expression", "value": "thinking" } ] }
```

- 各要素は `{ "type": <str>, **payload }` の形（`BotCommand.type` + `payload` 展開）。
  payload のキー（`target` / `value` / `reason` 等）はコマンド種別ごとに異なる。
- 未登録 device_id でもエラーにならず空配列を返す（キューが空なだけ）。
- 制御コマンドの種別カタログは design-spec §11.5 を参照。
- TODO(issue#8): WebSocket 配信（`websocket_bot_event_publisher`）へ置換予定。

ステータス: 200

### 2.3 `GET /api/bot/{device_id}/wakeword`（design-spec §11.6）

保存済み設定から有効な Wake Word 一覧を返す（`resolve_active_wake_words` で解決）。

Response 200（`WakeWordResponse`）:

```jsonc
{
  "enabled": true,
  "detection_method": "local",
  "wake_words": [
    { "id": "ww-1", "phrase": "hello bot", "model_name": "default", "threshold": 0.7, "enabled": true }
  ]
}
```

- 設定そのものは実動（SQLite 永続化）。検知処理（`DummyWakeWordDetector`）はダミー。
- 未登録 device_id は 404（`device not found`）。

ステータス: 200 / 404 / 422

---

## 3. Agent ルート（`backend/app/interfaces/api/agent_routes.py`）

両エンドポイントとも、Agent バックエンド失敗時（`AgentError`）は **5xx を返さず
200 + 安全フォールバック応答** を返す（design-spec §13 安定性 / ADR-0005）。
フォールバックは固定文 `"ごめんね、いまうまく考えられないみたい。もう一度話しかけてね。"`、
`emotion = "sad"`、`actions = [{type:"set_expression", value:"sad"}]`。

### 3.1 `POST /api/agent/chat`（design-spec §11.3）

Request（`AgentChatRequest`）:

```jsonc
{
  "device_id": "cores3-001",                 // 必須
  "message": "こんにちは",                    // 必須
  "context": { "wake_word_triggered": true } // 任意。既定 {}
}
```

Response 200（`AgentChatResponse`）:

```jsonc
{
  "text": "こんにちは、今日は何をしますか？",
  "emotion": "happy",
  "actions": [ { "type": "set_expression", "value": "happy" } ]
}
```

- `actions[].value` は `null` を取りうる（`AgentActionSchema`）。
- device の設定から `AgentProfile` を解決（未登録時は `AgentProfile()` 既定）。

ステータス: 200（成功・フォールバック双方）/ 422（バリデーション）

### 3.2 `POST /api/agent/proactive`（design-spec §11.7）

device 側イベント（注視検出など）から自発話しかけを生成する。**パスは
`/api/agent/proactive`**（design-spec §11.7 には現状パス未記載。§7 の差分参照）。

Request（`AgentProactiveRequest`）:

```jsonc
{
  "device_id": "cores3-001",            // 必須
  "event_type": "attention_detected",   // 任意。既定 "attention_detected"
  "context": {                           // 任意。既定 {}
    "face_detected": true,
    "attention_duration_ms": 1800,
    "last_proactive_talk_seconds_ago": 900,
    "conversation_active": false
  }
}
```

Response 200: `AgentChatResponse`（chat と同一スキーマ）。

```jsonc
{
  "text": "なにか手伝おうか？",
  "emotion": "curious",
  "actions": [
    { "type": "set_expression", "value": "curious" },
    { "type": "proactive_speak", "value": "attention_detected" }
  ]
}
```

- 実装は `proactive_speak` アクションの存在を保証する（無ければ `event_type` を
  `value` にして付与。`_ensure_proactive_action`）。
- 注意: design-spec §11.7 のサンプルでは `proactive_speak` に `reason` フィールドを
  持たせているが、実装の `AgentAction` は `type` / `value` のみ。値（event_type）は
  `value` に入る（§7 の差分参照）。

ステータス: 200（成功・フォールバック双方）/ 422

---

## 4. Speech / Vision ルート

### 4.1 `POST /api/speech/recognize`（design-spec §11.2）— ダミー

- リクエストボディ = 生バイト（`audio/wav` / `audio/pcm` を想定。実装は
  `await request.body()` で受け取るだけで Content-Type 検証はしない）。
- クエリ `device_id`（任意）。
- Response 200（`SpeechRecognizeResponse`）: `{ "text", "language", "confidence" }`。
- ダミー実装（`DummySpeechRecognizer`）は常に `text="こんにちは"`,
  `language=<設定の language>`, `confidence=0.92` を返す。
- TODO(issue#7): faster-whisper / sherpa-onnx 実装 + WS ストリーミング（§11.8）。

ファイル: `speech_routes.py` / `infrastructure/speech/dummy_speech_recognizer.py`

### 4.2 `POST /api/vision/detect`（design-spec §11.4）— ダミー

- リクエストボディ = 生バイト（`image/jpeg` / `image/raw` 想定。Content-Type 検証なし）。
- クエリ `device_id`（任意）。
- Response 200（`VisionDetectResponse`）:

```jsonc
{
  "detections": [
    { "type": "face", "bbox": { "x": 120, "y": 80, "width": 64, "height": 64 }, "confidence": 0.88 }
  ],
  "tracking_target": { "x": 152, "y": 112 }   // 無検出時は null
}
```

- ダミー実装（`DummyVisionRecognizer`）は常に上記の固定 face 検出を返す。
- TODO(issue#6/#8): OpenCV / ONNX による顔・動体検出と注視推定。

ファイル: `vision_routes.py` / `infrastructure/vision/dummy_vision_recognizer.py`

---

## 5. Settings ルート（`backend/app/interfaces/api/settings_routes.py`、design-spec §10）

設定集約 `BotSettings`（`domain/settings/entities.py`）を JSON で取得・更新する。
JSON 形は `settings_to_dict` / `settings_from_dict`（`infrastructure/persistence/serialization.py`）。

### 5.1 `GET /api/settings/{device_id}`

- Response 200: 設定集約の JSON（下記スキーマ）。
- 未登録 device_id は 404（`device not found`）。

### 5.2 `PUT /api/settings/{device_id}`

- Request body = 設定集約の **部分 JSON**（`dict`、既定 `{}`）。
- 動作: 現在値（無ければ `BotSettings.default(device_id)`）を dict 化し、その上に
  **トップレベルキー単位で** リクエストを浅くマージ（`{**current, **body}`）してから
  `settings_from_dict` で再構築・保存し、結果を返す。
  - 注意: マージは浅い。例えば `{"agent": {...}}` を送ると `agent` ブロック全体が
    リクエスト値で置換される（ただし `settings_from_dict` が各キー欠落をデフォルトで
    埋めるため、ブロック内の省略キーはデフォルトに戻る）。
- Response 200: 更新後の設定集約 JSON。
- 注意: 事前に `register` していない device でも PUT は 200 で成功する
  （`BotSettings.default` を土台にするため）。ただし Bot エンティティは作られないので
  Dashboard 一覧には現れない。

### 5.3 設定集約スキーマ（`settings_to_dict` 出力 / 既定値）

トップレベルキーと各ブロックの実フィールド（デフォルト値の根拠は各 domain entities）:

| キー | フィールド（既定値） |
|---|---|
| `device_id` | 文字列 |
| `agent` | `agent_type`("OpenAICompatible"), `model_name`("dummy-model"), `system_prompt`(""), `tools_enabled`(false), `memory_enabled`(false), `temperature`(0.7), `max_tokens`(512), `response_mode`("sync") |
| `speech` | `provider`, `model_name`, `language`("ja"), `vad_enabled`, `noise_reduction_enabled`, `streaming_enabled` |
| `conversation_turn` | `barge_in_enabled`, `aec_enabled`, `vad_threshold`, `vad_threshold_while_speaking`, `min_interruption_duration_ms`, `end_of_turn_silence_ms`, `semantic_end_of_turn_enabled`, `max_utterance_duration_ms`, `interrupt_behavior` |
| `vision` | `provider`, `model_name`, `face_tracking_enabled`, `motion_tracking_enabled`, `target_tracking_enabled`, `frame_interval_ms`, `resolution`, `processing_location` |
| `vision_stream` | `idle_fps`, `motion_detected_fps`, `face_detected_fps`, `tracking_fps`, `conversation_fps`, `resolution`, `jpeg_quality`, `send_only_on_motion`, `max_frame_size`, `processing_location` |
| `attention` | `enabled`, `require_face_centered`, `require_head_pose`, `require_gaze_estimation`, `attention_duration_ms`, `confidence_threshold` |
| `proactive_talk` | `enabled`, `cooldown_seconds`, `max_count_per_day`, `allow_without_wake_word`, `allow_during_conversation`, `disabled_in_focus_mode`, `disabled_at_night` |
| `wake_word` | `enabled`, `detection_method`, `max_local_active`, `wake_words`[`id`,`phrase`,`model_name`("default"),`threshold`(0.7),`enabled`(true)] |
| `display` | `brightness`, `theme`, `volume` |

> 各ブロックの個々の既定値は各 domain の entities / value_objects（`@dataclass(frozen=True)`）に従う。
> `settings_from_dict` は未知キーを無視し、欠落キーをデフォルトで埋めるため、後方互換性がある。

---

## 6. Dashboard / Health

### 6.1 `GET /` および `GET /dashboard`（design-spec §10）

- 登録済み Bot 一覧（device_id / name / firmware / status）を最小の HTML テーブルで返す
  （`HTMLResponse`）。設定パネルは未実装（後続フェーズ）。
- ファイル: `interfaces/dashboard/routes.py`。

### 6.2 `GET /health`

- Response 200: `{ "status": "ok" }`。

---

## 7. 実動 / ダミーの内訳と対応 Issue

| 領域 | 状態 | 実装 | 対応 Issue |
|---|---|---|---|
| Bot 登録 | 実動 | `register_bot.py` + SQLite | — |
| 設定 永続化（GET/PUT/wakeword 設定） | 実動 | `SqliteSettingsRepository` | — |
| コマンド取得 | 実動（ポーリング） | `InMemoryBotEventPublisher.drain` | TODO(issue#8) WS 化 |
| Agent: OpenAICompatible | 実動 | `OpenAICompatibleGateway`（httpx） | — |
| Agent: HermesAgent | スタブ（固定文 `[HermesAgent stub] ... (TODO issue#6)`） | `hermes_agent_gateway.py` | TODO(issue#6) |
| Agent: OpenClaw | スタブ（固定文 `[OpenClaw stub] ... (TODO issue#6)`） | `openclaw_gateway.py` | TODO(issue#6) |
| Agent: Dummy | テスト/フォールバック用固定応答 | `dummy_agent_gateway.py` | — |
| Speech 認識 | ダミー（固定 `こんにちは`） | `DummySpeechRecognizer` | TODO(issue#7) |
| Vision 検出 | ダミー（固定 face） | `DummyVisionRecognizer` | TODO(issue#6/#8) |
| WakeWord 検知 | ダミー（先頭の有効語を返す） | `DummyWakeWordDetector` | TODO(issue#7) |
| Dashboard | 実動（最小・一覧のみ） | `dashboard/routes.py` | 後続フェーズで設定 UI |
| 音声 WS ストリーミング（§11.8） | 未実装 | — | TODO(issue#8) Phase 8 |

---

## 8. 設定（環境変数 / `backend/app/config/settings.py`）

`AppSettings`（`pydantic-settings`）。環境変数 prefix は **`STACKCHAN_`**、`.env` 読み込み、
未知キーは無視（`extra="ignore"`）。`get_settings()` は `lru_cache` でプロセス内シングルトン。
URL・モデル名・閾値などはこのモジュールに集約（CLAUDE.md: ハードコード禁止）。

| 設定名（環境変数） | 既定値 | 用途 |
|---|---|---|
| `STACKCHAN_APP_NAME` | `"StackChan Backend"` | FastAPI title |
| `STACKCHAN_DATABASE_URL` | `"sqlite:///./stackchan.db"` | 設定永続化先 |
| `STACKCHAN_CORS_ALLOW_ORIGINS` | `["*"]` | CORS 許可 origin |
| `STACKCHAN_DEFAULT_AGENT_TYPE` | `"OpenAICompatible"` | Agent provider 選択（`AgentType` の値） |
| `STACKCHAN_DEFAULT_AGENT_MODEL` | `"dummy-model"` | 既定モデル名 |
| `STACKCHAN_AGENT_BASE_URL` | `"http://localhost:11434/v1"` | OpenAI 互換 base_url |
| `STACKCHAN_AGENT_API_KEY` | `""` | API Key（空なら Authorization ヘッダ無し） |
| `STACKCHAN_AGENT_REQUEST_TIMEOUT_S` | `30.0` | Agent リクエストのタイムアウト秒 |
| `STACKCHAN_DEFAULT_SPEECH_PROVIDER` | `"dummy"` | （現状ダミー） |
| `STACKCHAN_DEFAULT_SPEECH_LANGUAGE` | `"ja"` | 音声言語 |

> 注意: `default_agent_model` の既定が `"dummy-model"` のため、OpenAICompatible を実運用するには
> `STACKCHAN_DEFAULT_AGENT_MODEL` の上書きが事実上必須（device 設定の `agent.model_name` でも上書き可。
> `AgentProfile.model_name` 優先 → 無ければ設定 `default_agent_model`）。

---

## 9. AgentGateway の Provider 解決（registry 方式）

design-spec §13 / CLAUDE.md「if 文で Provider 分岐を増やさない」に従い、Provider 選択は
レジストリ（`infrastructure/agent/registry.py`）で行う。

- `AgentType`（`domain/agent/value_objects.py`）: `HermesAgent` / `OpenClaw` / `OpenAICompatible`。
- `_BUILDERS: dict[AgentType, GatewayBuilder]` が単一の選択ソース。Provider 追加 = builder 追加 +
  1 エントリ追加（if 分岐を増やさない）。
- `build_agent_gateway(settings)` が `settings.default_agent_type` を `AgentType` に解決し、
  対応 builder で具象を生成。**未設定・未知の値はデフォルト（`OpenAICompatible`）にフォールバック**
  （typo で起動が落ちない）。
- DI: `di_container/container.py` の `Container.__init__` で `build_agent_gateway` を 1 回呼んで
  シングルトン保持。`dependencies.get_agent_use_case` が `ProcessAgentRequestUseCase` に注入。

設定方法（例）:

```bash
# OpenAI 互換（Ollama 例）
export STACKCHAN_DEFAULT_AGENT_TYPE=OpenAICompatible
export STACKCHAN_AGENT_BASE_URL=http://localhost:11434/v1
export STACKCHAN_DEFAULT_AGENT_MODEL=llama3.1
# HermesAgent / OpenClaw（現状スタブ）
export STACKCHAN_DEFAULT_AGENT_TYPE=HermesAgent
```

OpenAICompatible の応答マッピング（`openai_compatible_gateway.py`）:

- モデルに `{"text","emotion","actions"}` の JSON を返すよう system で指示。
- JSON として解釈できればそのまま `AgentReply` に対応付け。
- できなければメッセージ本文全体を `text`、`emotion="neutral"`、`set_expression` アクションを合成。
- proactive は `proactive_speak` アクションの付与を保証。

---

## 10. エラー処理方針

| 状況 | 挙動 | 根拠 |
|---|---|---|
| Agent バックエンド失敗（timeout / 接続 / 非 2xx / 不正 body） | adapter が `AgentError` を送出 → ルートが捕捉し **HTTP 200 + 安全フォールバック応答**（warning ログ） | `agent_routes.py` / ADR-0005 / §13 |
| 未登録 device の GET settings / wakeword | 404 `device not found` | `settings_routes.py` / `bot_routes.py` |
| リクエストスキーマ不正 | 422（FastAPI/Pydantic 既定） | FastAPI |
| commands ポーリングで device 未登録 | 200 + 空配列（エラーにしない） | `InMemoryBotEventPublisher` |
| 設定 PUT で未登録 device | 200（default を土台に作成） | `settings_routes.py` |

- adapter は transport 固有例外（httpx 等）を `AgentError` でラップし、詳細を外へ漏らさない
  （`agent_gateway.py` ABC のコントラクト）。
- フォールバックの狙いは「firmware の会話ループを 1 ターンの失敗で壊さない」（§13 安定性）。

---

## 11. design-spec §11 との差分

実装が design-spec §11 と異なる / §11 が未記載の点（**実装を正とした差分**）:

| # | 項目 | design-spec §11 | 実装 | 備考 |
|---|---|---|---|---|
| 1 | 自発話しかけのパス | §11.7 に **パス未記載**（「backend → Agent」のリクエスト例のみ） | `POST /api/agent/proactive`（chat と別ルート、同一レスポンススキーマ） | 本 PR で §11.7 にパスを追記 |
| 2 | `proactive_speak` の構造 | `{type, reason, text}` を例示 | `AgentAction` は `{type, value}` のみ。`value` に event_type | スキーマ簡素化。firmware/Adapter 側で吸収想定（ADR-0004） |
| 3 | エラー時の HTTP 挙動 | §11 に明記なし | Agent 失敗時は **200 + フォールバック**（5xx を返さない） | ADR-0005 で決定。§13 と整合 |
| 4 | コマンド配信方式 | §11.5 GET ポーリング + §11.8 WS ストリーミング | 現状は **GET ポーリングのみ**（in-memory）。WS 未実装 | §11.8 は Phase 8 TODO(issue#8) |
| 5 | register の settings スキーマ | `{ "audio": {}, "display": {}, "wake_word": {}, "vision": {} }`（簡略例） | 実スキーマは §5.3 の集約（`agent`/`speech`/`conversation_turn`/`vision`/`vision_stream`/`attention`/`proactive_talk`/`wake_word`/`display`）。`audio` キーは無い | §11.1 は例示、実体は §5.3 |
| 6 | register の `capabilities` | リクエストに含む | 受理するが保存・反映しない | 将来対応余地 |
| 7 | Settings API | §10 にダッシュボード言及。エンドポイント詳細は §11 になし | `GET/PUT /api/settings/{device_id}`（部分マージ）。本書 §5 で規定 | §11 に settings 節が無い |
| 8 | Speech / Vision の入力形式 | `multipart/form-data` も挙げる | 実装は生ボディ（`request.body()`）のみ。Content-Type 検証なし | multipart は未対応 |
| 9 | Speech / Vision / WakeWord 検知 | 実機能前提の記述 | 全てダミー（固定応答） | §7 の Issue 参照 |

---

## 12. 関連ファイル

- ルート: `backend/app/interfaces/api/{bot,agent,speech,vision,settings}_routes.py`
- スキーマ: `backend/app/interfaces/api/schemas.py` / `backend/app/interfaces/dashboard/schemas.py`
- 設定: `backend/app/config/settings.py`
- Agent: `backend/app/application/ports/agent_gateway.py`,
  `backend/app/infrastructure/agent/{registry,openai_compatible_gateway,hermes_agent_gateway,openclaw_gateway,dummy_agent_gateway}.py`
- DI: `backend/app/di_container/{container,dependencies}.py`
- 永続化: `backend/app/infrastructure/persistence/{sqlite_settings_repository,serialization}.py`
- 設計の正: `docs/design-spec.md` §10 / §11 / §13、`docs/adr/0004`・`docs/adr/0005`
