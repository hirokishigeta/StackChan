# リポジトリ調査 (Phase 0)

本書は `docs/design-spec.md` の改修（CoreS3 を PC バックエンド連携の入出力端末化）に向けた既存リポジトリの調査結果である。調査の主対象は `firmware/`。
記載は**事実とファイルパス・行番号ベース**で行い、推測には「未確認」と明示する。コードは一切変更していない。

---

## 1. リポジトリ全体構成

モノレポ。改修対象は `firmware/` と新設 `backend/`（本 Phase では未作成）。

| ディレクトリ | 役割 | 技術スタック | 規模（概要） | 本改修での扱い |
|---|---|---|---|---|
| `firmware/` | CoreS3 ファームウェア。**調査の主対象** | C++ / ESP-IDF v5.5.4 / LVGL 9.4 / esp-sr / esp32-camera。外部依存 `xiaozhi-esp32`（後述） | `main/` 配下: main.cpp 約63行 + hal 約3,500行 + apps 約6,200行 + stackchan（アバター/モーション） | 改修の主対象 |
| `server/` | 公式クラウドサーバー（アカウント・アプリストア・XiaoZhi 連携） | Go / GoFrame v2 / MySQL | 未精査 | 改修対象外（ADR-0002 / 0003）。原則触らない |
| `app/` | モバイルアプリ（動画視聴・リモートアバター制御等） | Flutter / Dart | 未精査 | 改修対象外 |
| `remote/` | ESP-NOW リモコンファームウェア | C++ / ESP-IDF | 未精査 | 改修対象外 |

> `server/` `app/` `remote/` の内部構造は本 Phase では未精査（design-spec の主対象が firmware のため）。必要時に別途調査する。

### 1.1 firmware の依存取得方式（重要）

`firmware/fetch_repos.py` が `firmware/repos.json` を読み、外部リポジトリを `firmware/components/` 等へ clone する。中でも決定的に重要なのが:

- **`78/xiaozhi-esp32` v2.2.4**（`firmware/xiaozhi-esp32/` に展開、`patches/xiaozhi-esp32.patch` でパッチ適用）

`firmware/main/CMakeLists.txt`（1-65行）が xiaozhi-esp32 の `main/` から多数の `.cc` を直接コンパイル対象に取り込む。すなわち **AI 会話エンジン本体（音声・Wake Word・プロトコル・OTA・設定）は xiaozhi-esp32 側にあり、firmware/main/ はそれを起動・橋渡しする層**である。

CMakeLists で取り込む主な xiaozhi ソース:
`application.cc` / `audio/audio_service.cc` / `audio/audio_codec.cc` / `protocols/{protocol,mqtt_protocol,websocket_protocol}.cc` / `audio/wake_words/{afe_wake_word,custom_wake_word,esp_wake_word}.cc` / `audio/processors/afe_audio_processor.cc` / `ota.cc` / `settings.cc` / `mcp_server.cc` / `display/*` ほか。

その他依存（`firmware/main/idf_component.yml`）: esp-sr ~2.3.0、esp32-camera ^2.1.4、esp_audio_codec ~2.4.1、esp_codec_dev、lvgl ~9.4、esp_lvgl_port、78/esp-wifi-connect、espressif/button、led_strip、bmi270_sensor ほか。

---

## 2. firmware の構成

### 2.1 エントリフロー（`firmware/main/main.cpp`）

```
app_main()
  ├ mclog 初期化
  ├ GetHAL().init()                          ← HAL 全体初期化（下記 2.2）
  ├ ui_hal の delay/tick を HAL に接続
  ├ skip_mooncake 判定                        ← getXiaozhiConfig().startAiAgentOnBoot && warmRebootTarget<0
  │
  ├ (skip_mooncake==false) mooncake にローカルアプリ8個を installApp
  │     AppLauncher / AppAiAgent / AppAvatar / AppEspnowControl /
  │     AppAppCenter / AppEzdata / AppDance / AppSetup
  │   while(1): feedTheDog / updateHeapStatusLog / GetMooncake().update()
  │            isXiaozhiStartRequested() で break
  │   uninstallAllApps + DestroyMooncake
  │
  └ GetHAL().startXiaozhi()                   ← 戻らない（AI 会話モードへ）
```

ポイント:
- 起動直後は **mooncake（アプリランチャ）モード**。GUI 上で `AI.AGENT` を選ぶと `AppAiAgent::onOpen()`（`apps/app_ai_agent/app_ai_agent.cpp:44`）が `GetHAL().requestXiaozhiStart()` を呼び、全アプリを破棄して `startXiaozhi()` に入る。
- `startXiaozhi()`（`hal/hal.cpp:179`）は StackChan の `_stackchan_update_task` を core1 に生成（`xTaskCreatePinnedToCore`, stack 4096, prio 3, `hal.cpp:200`）後、`hal_bridge::start_xiaozhi_app()` を呼ぶ。
- `start_xiaozhi_app()`（`hal/board/hal_bridge.cc`）は **xiaozhi-esp32 の `Application::GetInstance().Run()`** を呼び、これが AI 会話のメインイベントループとなり戻らない。

### 2.2 初期化順序（`Hal::init()`, `hal/hal.cpp:23`）

```
nvs_flash_init → xiaozhi_board_init → xiaozhi_mcp_init → head_touch_init
  → io_expander_init → rtc_init → imu_init → servo_init → lvgl_init
```

- `xiaozhi_board_init()` は `hal_bridge::xiaozhi_board_init()` 経由で xiaozhi の `Board::GetInstance()` を初期化（ディスプレイ・音声コーデック・カメラ・ネットワーク等のハードはこの Board が保持）。
- `xiaozhi_mcp_init()` は xiaozhi の `McpServer` にロボット制御ツールを登録（後述 3）。

### 2.3 FreeRTOS タスク構成（firmware/main が直接生成するもの）

| タスク | 生成元 | 内容 |
|---|---|---|
| `stackchan` | `hal.cpp:200`（core1, stack4096, prio3） | AI 会話モード中の StackChan アバター/モーション更新、ステータスバー、リマインダ |
| メインタスク(app_main) | ESP-IDF | mooncake ループ → startXiaozhi |

> xiaozhi-esp32 内部（audio_service、protocol、afe 等）は独自にタスクを生成する。それらは未精査（xiaozhi 側実装）。

### 2.4 `hal/` 各モジュールの責務

| ファイル | 行数 | 責務 | クラウド依存 |
|---|---|---|---|
| `hal.cpp` | 353 | HAL 集約、システム（mac/reboot/heap/OTA確認）、xiaozhi 起動橋渡し、表示/音量ファサード、ウォームリブート | ― |
| `hal/board/hal_bridge.cc` | ― | xiaozhi `Board`/`Application` への橋渡し、表示ロック、xiaozhi 設定NVS(`xiaozhi`ns)、明るさ/音量永続化呼び出し | ― |
| `hal/board/stackchan.cc` | 600+ | 明るさ(`display`ns)・音量(`audio`ns)の NVS 永続化、バッテリ、Board 実装補助 | ― |
| `hal/board/stackchan_camera.{h,cc}` | ― | esp_video(V4L2) ベースのカメラ。フレーム取得・JPEG エンコード・`Explain()`(画像説明API) | `Explain` がサーバ依存 |
| `hal/board/cores3_audio_codec.{h,cc}` | ― | CoreS3 用音声コーデック（AW88298 出力 / ES7210 入力） | ― |
| `hal/board/stackchan_display.{h,cc}` | ― | LVGL ディスプレイ実装（アバター描画面） | ― |
| `audio.cpp` | 174 | マイクテスト録音/再生・波形取得（`audio_codec` 直接利用） | ― |
| `hal_servo.cpp` | 361 | サーボ（yaw/pitch）制御・ゼロ校正・角度NVS(`servo`ns) | ― |
| `hal_imu.cpp` | 58 | BMI270 IMU、Shake/PickUp イベント | ― |
| `hal_rtc.cpp` | 127 | PCF8563 RTC、タイムゾーン(`system`ns)、SNTP同期 | ― |
| `hal_head_touch.cpp` | 164 | Si12T 頭部タッチ（撫でジェスチャ HeadPetGesture） | ― |
| `hal_io_expander.cpp` | 91 | PY32 IO エクスパンダ（サーボ電源・レーザー等） | ― |
| `hal_ble.cpp` | 291 | BLE GATT（モバイルアプリ設定・Wi-Fi 設定受信） | △（モバイルアプリ連携） |
| `hal_espnow.cpp` | 184 | ESP-NOW（リモコン受信・送信・レーザー制御） | ― |
| `hal_ota.cpp` | 76 | OTA（xiaozhi `Ota` クラス利用） | ●（OTA URL がクラウド: `api.tenclass.net`） |
| `hal_network.cpp` | 140 | Wi-Fi 接続（xiaozhi Board/WifiManager）、SNTP | ― |
| `hal_mcp.cpp` | 149 | xiaozhi MCP サーバへロボット制御ツール登録 | △（MCP 自体は xiaozhi 用、ツール本体はローカル） |
| `hal_ws_avatar.cpp` | 521 | **クラウド WebSocket アバター/ビデオ通話**（カメラ送信・通話・テキスト・ダンス・リモート制御） | ●（クラウド） |
| `hal_account.cpp` | 259 | アカウント情報取得・デバイス名・アンバインド（HTTP） | ●（クラウド） |
| `hal_app_center.cpp` | 126 | アプリストアからアプリ一覧取得・OTA でアプリ起動 | ●（クラウド） |
| `hal_ezdata.cpp` | 465 | **クラウド MQTT (ezdata/uiflow2.m5stack.com)** によるリモート設定・ペアコード | ●（クラウド） |

`hal/utils/`: `secret_logic`（サーバURL・認証トークン生成）、`bleprph`（BLE peripheral）、`wifi_connect`、`ota`、`jpeg_to_image`、`motion_detector`。

### 2.5 `stackchan/`（アバター・モーション）

`stackchan/stackchan.h` の `StackChan` クラスが中核。`Modifiable` を継承し、以下を保持:
- `avatar::Avatar`（顔描画。`stackchan/avatar/`）
- `motion::Motion`（サーボ yaw/pitch。`stackchan/motion/{motion,servo,motion_math}.cpp`）
- `addon::{Left,Right}NeonLight`（RGB LED）
- `ObjectPool<Modifier>`（後述 modifiers）

`update()` で modifier → avatar → motion → neon を順に更新。JSON から `updateAvatarFromJson` / `updateMotionFromJson` / `updateNeonLightFromJson` で外部制御可能（**BLE/WebSocket からのリモート制御の受け口**）。

- **avatar**: `stackchan/avatar/` に skins(default) / decorators(angry,dizzy,heart,shy,sweat) / elements(emotion,feature,speech_bubble 等)。表情・装飾を要素合成で描画。
- **modifiers**（`stackchan/modifiers/`）: blink / breath / dance / head_pet / idle_expression / idle_motion / imu / speaking / timed。アバターとモーションの自律的なふるまい。
- **motion**: サーボ角度制御。`motion_math.cpp` のみホスト側テスト対象（`firmware/tests/motion_math_test.cpp`）。

### 2.6 `apps/`（mooncake ローカルアプリ）

| アプリ | 役割 | 主な HAL 呼び出し | クラウド依存 |
|---|---|---|---|
| `app_launcher` | アプリ一覧ランチャ（889行） | ― | ― |
| `app_ai_agent` | **AI 会話モードへ遷移**（79行、実体は xiaozhi 起動要求のみ） | `requestXiaozhiStart()` | ●（起動先が XiaoZhi） |
| `app_avatar` | **クラウド WS アバター/ビデオ通話**（710行） | `startWebSocketAvatarService()`, `onWs*` | ●（クラウド） |
| `app_app_center` | **アプリストア**（434行） | `fetchAppList()`, `launchApp()` | ●（クラウド） |
| `app_ezdata` | **クラウド MQTT 連携**（212行） | `startEzDataService()` | ●（クラウド） |
| `app_espnow_ctrl` | ESP-NOW リモコン操作（486行） | `startEspNow()`, `espNowSend()`, `setLaserEnabled()` | ― |
| `app_dance` | ダンス（BLE 経由のシーケンス受信、193行） | `startBleServer()` | △（BLE/アプリ） |
| `app_setup` | 設定メニュー（3,101行、後述 4） | 多数 | 一部 ●（Account/AppCenter系） |
| `app_template` | サンプル雛形 | ― | ― |

---

## 3. AI・音声・カメラ連携箇所（置き換え対象の中心）

### 3.1 音声認識・LLM 連携

**重要**: firmware/main 自身は音声認識・LLM 通信を実装していない。**xiaozhi-esp32 の `Application` と `protocols/`（websocket_protocol.cc / mqtt_protocol.cc）が担う**。`hal_bridge::start_xiaozhi_app()` → `Application::Run()`（`hal/board/hal_bridge.cc`）がそのエントリ。

- プロトコル: xiaozhi は **WebSocket または MQTT+UDP**（`protocols/websocket_protocol.cc`, `mqtt_protocol.cc`）で XiaoZhi サーバと通信。接続先・認証（WS の `url`/`token`、MQTT の `endpoint` 等）は **`api.tenclass.net` のプロビジョニング応答が NVS `websocket`/`mqtt` に書き込む**（`ota.cc:146-172`）。**詳細は §5b.4-5b.5 で精査済み**（fetch 後）。
- データ形式: 音声は **Opus（上り 16kHz mono 60ms / 下り はサーバ hello でネゴ、既定 24kHz）**。制御は JSON（`type`: tts/stt/llm/mcp/system/alert）。詳細スキーマは §5b.4。

**`hal_ws_avatar.cpp`（521行）は LLM/音声認識ではなく、M5Stack クラウド経由の「アバター遠隔制御・ビデオ通話・カメラ映像送信」用の独自 WebSocket**である（タスク指示書の「中心と推測」は要修正、下記 §9 参照）。
- URL: `secret_logic::get_server_url() + "/stackChan/ws?deviceType=StackChan"`（`hal_ws_avatar.cpp:66`）
- 認証: `Authorization` ヘッダに `secret_logic::generate_auth_token()`（同105-117行）
- 独自バイナリプロトコル `[1B type][4B big-endian len][payload]`（`sendPacket`, 440-479行）。DataType 一覧は 36-57行（Opus / Jpeg / ControlAvatar / ControlMotion / Camera/Audio stream / Call 系 / Heartbeat / DanceSequence / SetDeviceName 等）。
- 受信は `onWs*` シグナル（`hal.h:243-252`）で `app_avatar` へ配信（カメラ映像受信表示・通話 UI・リモートアバター/モーション制御・テキスト表示・ダンス）。
- カメラ送信: `captureAndSendFrame()`（378行）で `hal_bridge::board_get_camera()` から取得→`image_to_jpeg`→ 送信。送信間隔は 350ms（通常）/700ms（video mode）（169行）。

`secret_logic.cpp` の実装はすべて `__attribute__((weak))` のスタブ（URL 既定 `http://localhost:3000`、トークン `"hi-stack-chan"`）。**実運用の認証ロジックはビルド時に別実装で上書きされる想定**（リポジトリには含まれない＝proprietary と推測、未確認）。

### 3.2 Wake Word（esp-sr）

- **esp-sr ~2.3.0** を利用。Wake Word 検知・AFE・VAD・AEC は **xiaozhi-esp32 の `audio/wake_words/` と `audio/processors/afe_audio_processor.cc`** が実装（CMakeLists 138-146行で取り込み）。
- Kconfig（`Kconfig.projbuild:687-783`）で方式を選択:
  - `USE_AFE_WAKE_WORD`（Wakenet + AFE。ESP32-S3 + PSRAM が既定）
  - `USE_ESP_WAKE_WORD`（AFE なし Wakenet）/ `USE_CUSTOM_WAKE_WORD`（Multinet カスタム）/ `WAKE_WORD_DISABLED`
- 採用 Wake Word モデル: **`CONFIG_SR_WN_WN9_HISTACKCHAN_TTS3=y`**（`sdkconfig.defaults:13`）=「ハイ、スタックチャン」相当。
- `USE_AUDIO_PROCESSOR`（ノイズ抑制）既定 `y`。
- **AEC**: `USE_DEVICE_AEC` 既定 `n`。`depends on` のボードリスト（`Kconfig.projbuild:749-758`）に **`BOARD_TYPE_M5STACK_STACK_CHAN` が含まれない** → 現状デバイス側 AEC は Kconfig 上選択不可。`USE_SERVER_AEC`（サーバ側AEC）も既定 `n`。
  → **design-spec §7.2 への回答（fetch 後に確定、詳細 §5b.6）**:
    - AFE（NS/VAD、必要なら AEC）の**コード経路は実装済み**（`afe_audio_processor.cc:40-67,189-198`）で S3+PSRAM なら動作する。**ブロッカーは「Kconfig の `depends on` 行に StackChan が無い」ことだけ**で、ハード制約ではない。
    - CoreS3 のコーデックは**スピーカー参照 ch を持つ**（`config.h:8` `AUDIO_INPUT_REFERENCE=true`、`cores3_audio_codec.cc` で 2ch=mic+参照）。AEC に必要な参照信号経路はハード的に存在。
    - **バージイン機構も xiaozhi に既存**: AEC 有効時 `kListeningModeRealtime`（Speaking 中も録音継続）に自動で切り替わる（`application.cc:953`）。
    - **見込み**: `USE_DEVICE_AEC` の `depends on` に `BOARD_TYPE_M5STACK_STACK_CHAN` を追加（1 行パッチ）+ `sdkconfig` で有効化すれば、CoreS3 でデバイス側 AEC とバージインが**有効化できる見込みが高い**。残るは実機での音響分離・参照信号品質の検証のみ（→ Phase 8 のブロッカーは大きく後退）。

### 3.3 マイク入力 / スピーカー出力 / コーデック（I2S）

- I2S 構成（`hal/board/config.h:8-21`）:
  - `AUDIO_INPUT_SAMPLE_RATE = 24000` / `AUDIO_OUTPUT_SAMPLE_RATE = 24000`
  - `AUDIO_INPUT_REFERENCE = true`（参照信号あり = AEC 用の出力参照を入力に含む構成）
  - GPIO: MCLK=0, WS=33, BCLK=34, DIN=14, DOUT=13。コーデック I2C: SDA=12, SCL=11
  - 出力コーデック **AW88298**、入力コーデック **ES7210**（マルチchマイク+参照）
- `audio.cpp`: マイクテスト（録音3秒→再生）・波形取得を `Board::GetAudioCodec()` 直叩きで実装。`input_channels()` を見て複数ch（mic+reference）を扱う（48-79行）。
- コーデック実体: `hal/board/cores3_audio_codec.cc` + xiaozhi の `audio/codecs/*`（box/es8311/es8374 等を CMakeLists で取り込み。CoreS3 は ES7210+AW88298 構成）。`esp_audio_codec` / `esp_codec_dev` を利用。

### 3.4 カメラ（esp32-camera / esp_video）

- `hal/board/stackchan_camera.{h,cc}`。**esp_video（V4L2 インターフェース）**ベース（`esp_video_init`, `video_fd_`, mmap バッファ）。xiaozhi の `Camera` を継承。
- センサ: **GC0308**（`sdkconfig.defaults:53-54`: `CONFIG_CAMERA_GC0308=y`, `CONFIG_CAMERA_GC0308_DVP_YUV422_320X240_20FPS=y`）→ 解像度 **320x240, YUV422, 20FPS**。
- 用途: ① WS アバターのビデオ送信（`captureAndSendFrame`）、② `Explain(question)` による画像説明（サーバへ JPEG+質問送信、`explain_url_`/`explain_token_`）。回転対応は `CONFIG_XIAOZHI_ENABLE_ROTATE_CAMERA_IMAGE` で条件コンパイル。
- design-spec §5（適応的フレーム送信）に向けては、フレーム取得・JPEG エンコード経路（`StreamCaptures()` / `image_to_jpeg`）が流用可能。送信先を backend へ差し替える。

---

## 4. 設定管理

### 4.1 保存方式

- **ローカル永続化は xiaozhi-esp32 の `Settings` クラス（NVS ラッパー、`xiaozhi-esp32/main/settings.cc`）**。`Settings(namespace, writable)` + `GetInt/SetInt/GetBool/SetBool/GetString/SetString`。
- `hal_ezdata.cpp` の "EzData" は**ローカル設定ストアではなくクラウド MQTT**（`ezdata2.m5stack.com` / `uiflow2.m5stack.com`）。リモートからのサーボ角度操作・ペアコード取得用。**設定保存方式として転用しない**（削除対象、§6）。

### 4.2 NVS 名前空間と設定項目

| NVS namespace | キー | 内容 | 設定元 | design-spec §3.1 「維持する画面系設定」該当 |
|---|---|---|---|---|
| `display` | `brightness` | バックライト明るさ | `stackchan.cc:609`, setup/Brightness | ● 明るさ |
| `audio` | `output_volume` | スピーカー音量 | `stackchan.cc:631-646`, setup/Volume | ● 音量 |
| `system` | （timezone） | タイムゾーン | `hal_rtc.cpp:118-125`, setup/Timezone | ○（端末系） |
| `servo` | `*.ANGLE`/`*.SPEED` 等 | サーボ角度・速度・校正 | `hal_servo.cpp` | ○（モーション基本） |
| `xiaozhi` | `idle_sec`/`ext_pwr`/`idle_lv`/`boot_ai` | アイドルシャットダウン秒・充電中シャットダウン許可・アイドル動作レベル・起動時AI自動開始 | `hal_bridge.cc:23-26,126-145`, setup/AI.Agent | △（端末動作。AI 自動起動は要再設計） |
| `stackchan` | `device_name` | デバイス名 | `hal_ws_avatar.cpp:31-32,259` | ● デバイス名（ただし WS 経由で設定される点に注意） |
| `account` | `username`/`device_name` | アカウント名・デバイス名 | `hal_account.cpp:16-18` | クラウド依存（削除対象） |
| `app_config` | `is_configed` | Wi-Fi/アプリ設定完了フラグ | `hal_ble.cpp:112-113` | ○（オンボーディング状態） |
| `warm_boot` | `app_index` | ウォームリブート先アプリ | `hal.cpp:325-326` | ○（内部） |

> Wi-Fi SSID/Password は xiaozhi の WifiManager / `esp-wifi-connect` が管理（独自 NVS）。具体的キーは未精査。
> design-spec §3.1 が要求する「Backend Server URL / Device ID / API Key」相当の設定は**現状存在しない**（新規追加が必要、Phase 1-3）。

---

## 5. 画面・表情表示

- **LVGL 9.4** + `esp_lvgl_port` + xiaozhi の `display/lvgl_display/*`。ディスプレイ実体は `StackChanAvatarDisplay`（`hal_bridge.cc` の `DISPLAY_TYPE`）。解像度 **320x240**（`config.h:30-31`）。
- 入力: `Hal::lvgl_init()`（`hal.cpp:303-317`）で LVGL タッチ indev を作成。タッチ座標は `hal_bridge::get_data().touchPoint` 経由。
- UI フレームワーク: `smooth_ui_toolkit`（`uitk::lvgl_cpp::*`）と `mooncake`（アプリ/Ability ライフサイクル）。`uitk::Signal<>` でイベント配信（`hal.h` の `onWs*`/`onBle*`/`onImu*` 等）。
- **表情・アバター描画**: `stackchan/avatar/`（§2.5）。要素合成 + decorator + modifier で構成。JSON 駆動（`updateAvatarFromJson`）。
  - design-spec の表情制御（`set_expression` コマンド §11.5、TurnState/VisionState に応じた表情）は、**この avatar + modifier 機構と `updateAvatarFromJson` 経路をほぼそのまま流用可能**。現状 WS/BLE から流れている JSON 制御を backend からの制御に差し替える形が自然。

---

## 5b. xiaozhi-esp32 内部構造（fetch 後に精査）

`firmware/xiaozhi-esp32/`（`78/xiaozhi-esp32`、`patches/xiaozhi-esp32.patch` 適用済み）を精査した結果。AI 会話の本体はここの `Application`。ファイルは `firmware/xiaozhi-esp32/main/` 配下。

### 5b.1 Application 状態機械

- 状態定義: `device_state.h`。`enum DeviceState`: Unknown / Starting / WifiConfiguring / **Idle** / Connecting / **Listening** / **Speaking** / Upgrading / **Activating** / AudioTesting / FatalError。
- 状態機械本体は `device_state_machine.{h,cc}`（リスナー登録式）。`Application::SetDeviceState()`（`application.cc:57`）で遷移、`MAIN_EVENT_STATE_CHANGED` 経由で `HandleStateChangedEvent()`（`application.cc:858`）が LED/表情/音を更新。
- 主な遷移（会話 1 ターン）: `Idle →(ToggleChat/WakeWord)→ Connecting →(OpenAudioChannel)→ Listening →(tts start)→ Speaking →(tts stop)→ Listening or Idle`。
- design-spec §7.3 の TurnState との対応: Idle↔Idle、Listening↔UserSpeaking、（Thinking は xiaozhi に明示状態なし＝サーバ側で処理）、Speaking↔BotSpeaking、Interrupted は **AbortSpeaking**（`application.cc:940`）で表現（Speaking 中の WakeWord/手動で `kAbortReasonWakeWordDetected` を送り Listening に戻す）。

### 5b.2 音声パイプライン（`audio/audio_service.cc`）

```
[ES7210 mic + 参照ch] → AudioInputTask
   → AfeAudioProcessor(AFE: NS/VAD/(AEC)) → WakeWord(afe/esp/custom)
   → OpusEncode(16kHz mono 60ms) → send_queue
   → Application::Run() の MAIN_EVENT_SEND_AUDIO で protocol_->SendAudio()
[protocol 受信(Opus)] → OnIncomingAudio → PushPacketToDecodeQueue
   → OpusCodecTask が decode → playback_queue → AudioOutputTask → [AW88298 spk]
```

- FreeRTOS タスク（`audio_service.cc:125-167`、`AudioService::Start()`）:
  | タスク | prio / stack / core | 役割 |
  |---|---|---|
  | `audio_input` | 8 / 6KB / core0 | コーデック読み取り → AFE → WakeWord Feed → エンコードキュー投入 |
  | `audio_output` | 4 / 4KB | 再生キュー → コーデック書き込み |
  | `opus_codec` | 2 / 24KB | Opus エンコード（送信用）/ デコード（再生用） |
  - これらは `Application` の `Run()` メインタスク（prio 10、`application.cc:167`）とは別。`Application` は event group（`MAIN_EVENT_*`）でこれらと結合。
- Opus パラメータ: **エンコード（上り）= 16kHz / mono / 60ms フレーム**（`audio_service.h:39,66`）。**デコード（下り）= サーバ hello でネゴ（既定 24kHz）**（`protocol.h:86` `server_sample_rate_=24000`）。
- VAD/WakeWord 検知はコールバックで `Application` に通知（`application.cc:80-85`）→ `MAIN_EVENT_WAKE_WORD_DETECTED` / `MAIN_EVENT_VAD_CHANGE`。

### 5b.3 Protocol 抽象（`protocols/protocol.h` — 置き換え設計の要）

`Protocol` は純粋仮想の薄い抽象クラス。`Application` はこの 1 インターフェースだけに依存する（`application.cc:498-609` の `InitializeProtocol()` で全コールバックを配線）。

- 受信コールバック（基底が保持、`protocol.cc`）: `OnIncomingAudio` / `OnIncomingJson` / `OnAudioChannelOpened` / `OnAudioChannelClosed` / `OnNetworkError` / `OnConnected` / `OnDisconnected`。
- 純粋仮想: `Start()` / `OpenAudioChannel()` / `CloseAudioChannel()` / `IsAudioChannelOpened()` / `SendAudio()` / `SendText()`。
- 既定実装あり（JSON 文字列を組み立て `SendText()` に流すだけ、`protocol.cc:42-79`）: `SendWakeWordDetected` / `SendStartListening` / `SendStopListening` / `SendAbortSpeaking` / `SendMcpMessage`。
- 実装は 2 つ: `WebsocketProtocol`（`protocols/websocket_protocol.cc`）と `MqttProtocol`（`protocols/mqtt_protocol.cc`）。`InitializeProtocol()` が OTA 応答の有無で選択（`application.cc:480-487`）。
- **クラウド固有処理は Protocol 実装側にほぼ閉じている**。`Application` 側に残るクラウド依存は (a) `Ota`（activation / version check / mqtt・websocket 設定取得、`application.cc:398-471` `CheckNewVersion`/`ActivationTask`）と (b) JSON メッセージ種別の解釈（後述 5b.5）のみ。`Application` 自体は接続先 URL・認証を一切持たない。

### 5b.4 XiaoZhi プロトコル詳細

共通: 制御は JSON、音声は Opus。1 メッセージに `session_id` と `type` を含む。

**WebSocket**（`websocket_protocol.cc`）— backend 連携の参考に最有力:
- 接続先・認証は **NVS namespace `websocket`** から取得（`OpenAudioChannel`, `websocket_protocol.cc:84-90`）: `url` / `token`（`Bearer ` 前置）/ `version`。
- HTTP ヘッダ: `Authorization: Bearer <token>` / `Protocol-Version` / `Device-Id`(MAC) / `Client-Id`(UUID)（93-110行）。
- ハンドシェイク: クライアント `hello`（`GetHelloMessage`, 203-226行）を送信 → サーバ `hello`（`session_id` と `audio_params.sample_rate`/`frame_duration`）待ち（最大 10 秒, 189行）。
  - クライアント hello: `{type:hello, version:<2|3>, features:{aec?, mcp:true}, transport:"websocket", audio_params:{format:"opus", sample_rate:16000, channels:1, frame_duration:60}}`。
- 音声フレーム: バイナリ WebSocket。`version==2` は `BinaryProtocol2`（version/type/reserved/**timestamp(server-side AEC 用)**/payload_size + Opus）、`version==3` は `BinaryProtocol3`（type/reserved/payload_size + Opus）、それ以外は生 Opus（`SendAudio`/`OnData`, 28-58/112-147行）。
- 制御メッセージ（上り、JSON テキスト）: `listen`(state=start/stop/detect, mode=auto/manual/realtime) / `abort`(reason) / `mcp`(payload) / `hello`。

**MQTT + UDP**（`mqtt_protocol.cc`）:
- 制御は MQTT（NVS namespace `mqtt`: `endpoint`/`publish_topic`/`username`/`password` 等、65-73行）。音声は **別 UDP チャネルを AES-CTR 暗号化**（nonce にシーケンス/timestamp、168-189行）。backend 連携には不向き（WebSocket 案を採る）。

**受信 JSON 種別**（`Application::InitializeProtocol` の `OnIncomingJson`, `application.cc:521-607`）:
| type | 中身 | Application の挙動 |
|---|---|---|
| `tts` | state=start/stop/sentence_start, text | start→Speaking, stop→Listening/Idle, sentence_start→ `display->SetChatMessage("assistant", text)` |
| `stt` | text（認識結果） | `SetChatMessage("user", text)`（ログ `>>`） |
| `llm` | emotion | `display->SetEmotion(emotion)` ← **表情連動の入口** |
| `mcp` | payload | `McpServer::ParseMessage()`（デバイス制御 RPC） |
| `system` | command=reboot | `Reboot()` |
| `alert` | status/message/emotion | `Alert()` |
| `custom` | payload | `CONFIG_RECEIVE_CUSTOM_MESSAGE` 時のみ表示 |

> **示唆**: design-spec §11.5 の `set_expression` は xiaozhi の `llm.emotion`、`stt`/`tts.sentence_start` は部分認識・発話テキスト、`mcp` は §11.5 のデバイス制御コマンドにそれぞれ対応する。backend が同じ JSON スキーマを話せば `Application` を温存できる。

### 5b.5 OTA / アクティベーション / 設定取得（`ota.cc`）

- `Ota::CheckVersion()`（`ota.cc:85-`）が `CONFIG_OTA_URL`（既定 `https://api.tenclass.net/xiaozhi/ota/`、NVS `wifi.ota_url` で上書き可、`ota.cc:46-50`）へ POST。
- 応答 JSON から: `firmware`(OTA url/version) / `activation`(code/challenge/message/timeout_ms) / **`mqtt` セクション → NVS `mqtt`** / **`websocket` セクション → NVS `websocket`** を書き込む（`ota.cc:146-172`）。
- つまり **「接続先 WS/MQTT URL とトークンを払い出すプロビジョニングサーバ」が `api.tenclass.net`**。`WebsocketProtocol` は払い出された NVS `websocket.url`/`token` を読むだけ。
- アクティベーション: `ActivationTask`（`application.cc:323-`）/ `CheckNewVersion`（398-471行）で `Ota::Activate()` をリトライ。**パッチで `ShowActivationCode()` の音声読み上げを無効化し「Please bind and set up in the mobile app.」表示に置換**（patch / `application.cc:612-643`）。

### 5b.6 AEC・VAD・バージイン（`audio/processors/afe_audio_processor.cc`）

- AFE 構成（`afe_audio_processor.cc:40-67`）: `afe_config_init(input_format, NULL, AFE_TYPE_VC, AFE_MODE_HIGH_PERF)`。`aec_mode=AEC_MODE_VOIP_HIGH_PERF`、`vad_mode=VAD_MODE_0`、NS 有効。
- AEC は `#ifdef CONFIG_USE_DEVICE_AEC` で `aec_init=true`（このとき `vad_init=false`）。**AEC のコード経路自体は実装済み**で S3+PSRAM なら動作する（`EnableDeviceAec`, 189-198行）。
- **バージインは xiaozhi に既に存在**: `Application::GetDefaultListeningMode()`（`application.cc:953`）は **AEC が有効なら `kListeningModeRealtime`（全二重・Speaking 中も録音継続＝バージイン）**、無効なら `kListeningModeAutoStop`。`SetAecMode()`（`application.cc:1081`）で device/server AEC を切替。
- CoreS3 のコーデックは **参照 ch あり**（`hal/board/config.h:8` `AUDIO_INPUT_REFERENCE=true`、`cores3_audio_codec.cc:13-14` で 2ch=mic+参照）。AEC に必要なスピーカー参照信号経路はハード的に存在する。

---

## 6. 既存クラウド接続の削除範囲（ADR-0003）

### 6.1 クラウド依存コードのファイル単位リスト

| ファイル / 機能 | 依存先 | 内容 |
|---|---|---|
| `hal/hal_ws_avatar.cpp` | `secret_logic::get_server_url()` + 独自WS, カメラ, 通話 | クラウドアバター/ビデオ通話/カメラ送信 |
| `hal/hal_account.cpp` | `secret_logic` + HTTP `/stackChan/device/*` | アカウント・デバイス名・アンバインド |
| `hal/hal_app_center.cpp` | `secret_logic` + HTTP `/stackChan/apps` + OTA | アプリストア取得・アプリ起動 |
| `hal/hal_ezdata.cpp` | `ezdata2.m5stack.com` / `uiflow2.m5stack.com` (HTTP+MQTT) | リモート設定・ペアコード |
| `hal/utils/secret_logic/*` | ― | クラウド URL/認証トークン生成（weak スタブ） |
| `apps/app_avatar/*` | `startWebSocketAvatarService`, `onWs*` | WS アバター UI（710行） |
| `apps/app_app_center/*` | `fetchAppList`, `launchApp` | アプリストア UI（434行） |
| `apps/app_ezdata/*` | `startEzDataService` | EzData UI（212行） |
| `apps/app_ai_agent/*` | `requestXiaozhiStart` → XiaoZhi 起動 | AI 会話起動（接続先が XiaoZhi クラウド） |
| **xiaozhi-esp32 の `Ota` + プロビジョニング** | `api.tenclass.net`（version/activation/接続先払い出し） | OTA URL・activation・WS/MQTT 接続先払い出し。**ここがクラウド依存の実体**（`ota.cc`）。`Application`/`protocols/`/wake word/audio service は接続先非依存で再利用可（§8.1 案A） |
| xiaozhi `protocols/{websocket,mqtt}_protocol.cc` | NVS `websocket`/`mqtt`（接続先） | 接続先は払い出し由来。**backend 用 `Protocol` 実装の追加で差し替え**（削除ではなく差し替え、§8.1） |
| `app_setup` の Account サブ | `hal_account` | `apps/app_setup/workers/account.cpp` |

### 6.2 残す機能との依存関係（削除すると壊れるもの）

| 残す機能 | 実装 | クラウド削除の影響 |
|---|---|---|
| OTA | `hal_ota.cpp`（xiaozhi `Ota`） | OTA URL がクラウド（`api.tenclass.net`）。配信元の再決定が必要（ADR-0003「影響」/別ADR）。コード自体は残せる |
| BLE | `hal_ble.cpp` | 独立。ただし用途はモバイルアプリ設定/Wi-Fi 設定。**Wi-Fi 設定受信機構は残す価値あり** |
| ESP-NOW | `hal_espnow.cpp`, `app_espnow_ctrl` | 独立。クラウド非依存。残す |
| サーボ/IMU/タッチ/RTC | `hal_servo/imu/head_touch/rtc.cpp` | 独立。残す |
| 画面/アバター | `stackchan/`, `hal/board/stackchan_display.cc`, LVGL | 独立。残す（表情制御の流用先） |
| マイク/スピーカー/カメラ HAL | `audio.cpp`, `cores3_audio_codec.cc`, `stackchan_camera.cc` | コーデック/カメラ取得は独立。ただし **音声・カメラの「送信先・会話制御」は xiaozhi `Application` と密結合** → backend 連携に置換が必要 |
| ローカル設定 | NVS `Settings`（display/audio/system/servo） | 独立。残す |

**最大の論点（削除すると壊れる中核）**: **xiaozhi-esp32 の `Application`**。これは「Wake Word 検知 → 音声送信 → AI 応答 → スピーカー再生 → MCP ツール → 表情連動」を一体で持つ。`hal_mcp.cpp`（ロボット制御ツール）・`audio.cpp`・カメラ・アバター更新・OTA・Wake Word が全部この上に乗る。**単純削除は不可**。
ただし fetch 後の精査（§5b/§8.1）で、**`Application` 自体は接続先・認証を持たず `Protocol` 抽象 1 点にのみ依存する**ことが判明した。したがって「`Application` を温存し backend 用 `Protocol` 実装に差し替える（案A）」が最小工数で成立する。削除すべきクラウド依存の実体は `Application` ではなく **`Ota`（`api.tenclass.net` への activation/接続先払い出し）**。

### 6.3 3分類

**A. 即削除可能**（他のローカル機能が依存しない、クラウド専用）:
- `apps/app_app_center/*` + `hal_app_center.cpp`（アプリストア。`fetchAppList`/`launchApp` の参照元は app_app_center のみ）
- `apps/app_ezdata/*` + `hal_ezdata.cpp`（参照元は app_ezdata のみ）
- `app_setup` の Account サブメニュー + `hal_account.cpp`（参照元は account.cpp / about.cpp）

> いずれも `apps.h` の install 列挙（`main.cpp:35-41`）と setup メニュー（§4 の menu_sections）から外せば本体機能は壊れない。`launchApp` は OTA を呼ぶため OTA ユーティリティは残す。

**B. 分離してから削除**（ローカル機能と配線が絡む）:
- `hal_ws_avatar.cpp` + `apps/app_avatar/*`: カメラ取得・JPEG エンコード・`updateAvatar/MotionFromJson` 経路は流用したいので、**WS 通信部分のみ分離**してから削除し、カメラ/制御経路は backend クライアントへ移す。
- `app_ai_agent` + xiaozhi `Application`: **backend 連携クライアント（音声 WS / Agent API / Wake Word）を新設してから**置換。これが改修の本丸。
- `hal_mcp.cpp`: ツール本体（yaw/pitch/LED/reminder）はローカル能力。MCP（xiaozhi）依存を外し、backend 制御コマンド（design-spec §11.5）受信器へ移植。

**C. クラウド依存だが一部ロジックを backend 連携に転用可能**:
- カメラ送信パイプライン（`captureAndSendFrame`, `image_to_jpeg`, `StreamCaptures`）→ design-spec §5 の適応的フレーム送信の土台。
- 独自バイナリ WS プロトコル（`hal_ws_avatar.cpp` の type/len/payload）→ backend の WS（design-spec §11.8）設計の参考。Opus/Jpeg/Control 系の分類はそのまま活かせる。
- リモートアバター/モーション JSON 制御（`updateAvatarFromJson` 等）→ backend の `set_expression`/`look_at` 等のコマンド適用先。
- BLE の Wi-Fi 設定受信（`hal_ble.cpp` の WifiConfigServer）→ Backend URL / Device ID 設定の受け口に拡張可能。

---

## 7. ハードウェア仕様（CoreS3）

| 項目 | 値 | 出典 |
|---|---|---|
| SoC | ESP32-S3（240MHz dual-core） | README, `sdkconfig.defaults:4` |
| Flash | 16MB（QIO） | README, `sdkconfig.defaults:7-8` |
| PSRAM | 8MB（SPIRAM, 80MHz） | README, `sdkconfig.defaults:27-28`（容量はREADME。sdkconfig は有効化のみ） |
| ディスプレイ | 2.0" 静電容量タッチ, 320x240 | README, `config.h:30-31` |
| カメラ | GC0308, 0.3MP, 320x240 YUV422 20FPS | README, `sdkconfig.defaults:53-54` |
| マイク | デュアルマイク（ES7210 入力、参照ch あり） | README, `config.h`（`AUDIO_INPUT_REFERENCE=true`） |
| スピーカー | 1W（AW88298 出力） | README, `config.h:20` |
| I2S サンプルレート | 入出力 24kHz | `config.h:8-10` |
| IMU | BMI270 系（9軸） | README, `hal_imu.cpp`, idf_component(bmi270_sensor) |
| RTC | PCF8563 | `hal_rtc.cpp`, drivers/PCF8563_Class |
| 頭部タッチ | Si12T（3ゾーン） | `hal_head_touch.cpp`, drivers/Si12T |
| サーボ | yaw 360°連続 / pitch 90°（フィードバックサーボ） | README, drivers/FTServo_Arduino |
| RGB LED | 12個（2列） | README, neon_light |
| 接続 | Wi-Fi / BLE（NimBLE） | `sdkconfig.defaults:18-23` |
| パーティション | ota_0/ota_1 各 ~4.9MB, assets(spiffs) 4MB, coredump 64KB | `partitions.csv` |

- **要実機確認**: PSRAM/Flash の実搭載量（sdkconfig は構成値、README は公称 8MB/16MB で整合）、デュアルマイク間距離・マイクアレイとしての発話方向推定可否（design-spec §9）、デバイス側 AEC の実用性（§3.2）。

---

## 8. 改修方針への示唆

**活かす**:
1. `stackchan/`（avatar/motion/modifiers/neon）と LVGL/mooncake UI 基盤。表情・視線・モーション制御は JSON 駆動経路ごと流用（design-spec §11.5 のコマンド適用先）。
2. ローカル HAL（servo/imu/head_touch/rtc/io_expander/espnow/audio コーデック/カメラ取得）。クラウド非依存で再利用可能。
3. NVS `Settings` による display/audio/system 設定（design-spec §3.1 の画面系設定維持）。
4. カメラ取得→JPEG エンコード パイプラインと WS バイナリプロトコル設計（§5, §11.8 の土台）。
5. BLE/Wi-Fi 設定受信機構（Backend URL/Device ID 設定の入口に拡張）。

**書き直す / 新設する**:
1. **AI 会話の中核の置換**（最大作業。Phase 3-8）。WebSocket 双方向ストリーミング（音声上り/TTS+制御下り、§7.6/§11.8）。**実装案は 2 通り（下記 8.1 で比較）**。
2. Wake Word は当面 esp-sr/AFE をローカル維持しつつ、検知 → backend 通知の抽象を入れる（design-spec §8.3「初期は既存方式維持」）。xiaozhi 既存の `SendWakeWordDetected`/`listen state=detect` がそのまま使える（§5b.3-5b.4）。
3. AEC/バージイン: Kconfig の `USE_DEVICE_AEC` depends-on に StackChan を追加 + 有効化（§3.2/§5b.6）。実機検証のみ残る。
4. 設定追加: Backend URL / Device ID / API Key（現状なし、§4.2）。WS 案なら NVS `websocket.url`/`token` を流用できる（§5b.4）。
5. CLAUDE.md の段階分離方針（domain/application/infrastructure/presentation）に沿い、`hal/` を infrastructure/hardware として温存しつつ新規モジュールから新構造へ。**main.cpp に処理を足さない**。

### 8.1 Protocol 差し替え案 vs Application 置き換え案（最重要）

design-spec §11.8（`WS /api/bot/{device_id}/audio`）と §7（TurnState/バージイン）を実装する際の 2 案。

| 観点 | **案A: backend 用 Protocol 実装を追加し Application を温存** | 案B: Application ごと自前実装に置換 |
|---|---|---|
| 概要 | `Protocol` を継承した `BackendProtocol`（WebSocket）を新規実装し、`InitializeProtocol()`（`application.cc:480-487`）の選択分岐に差し込む。`Application`・`AudioService`・WakeWord・MCP・表情連動はそのまま | `Application`/`AudioService` 相当を firmware/main 側に新規実装し、xiaozhi は HAL（Board/Codec/Camera）と AFE/Opus のみ利用 |
| 抽象の境界 | **非常にきれい**。`Protocol` は純粋仮想 6 メソッド + 7 コールバック（§5b.3）。`Application` は接続先・認証を一切持たず Protocol 1 点に依存 | Application を作り直す必要があり、状態機械・event group・5 タスク連携を再実装 |
| backend に必要な対応 | backend が xiaozhi JSON スキーマ（hello/listen/tts/stt/llm/mcp、§5b.4）と Opus を話す | backend は design-spec のスキーマ（§11）を自由に定義可能 |
| 音声フォーマット | Opus（上り16k/下り24k）。backend に Opus enc/dec が必要 | PCM 直送も選べる（design-spec §11.8 は PCM 想定） |
| 既存資産の再利用 | AFE/VAD/WakeWord/AEC/バージイン/表情連動/MCP を**そのまま流用**。改修量が最小 | 同等機能を再実装するため改修量大 |
| クラウド除去 | `Ota`（activation/version、`api.tenclass.net`）の無効化と、NVS `websocket` を backend 設定で埋める手段の新設が必要 | Ota ごと不要にできる |
| design-spec 準拠 | backend 側 API スキーマを xiaozhi 互換に寄せる必要（§11 と差異）。Adapter で吸収可 | design-spec の API（§11）にそのまま合わせられる |
| リスク | xiaozhi のバージョンアップ追従（パッチ運用）。スキーマがクラウド前提の項目を含む | 状態機械・タスク・AEC 連携のバグ作り込みリスク大、工数大 |

**推奨: 案A（Protocol 差し替え）を基本とし、backend の WS API を「xiaozhi 互換 + 拡張」で設計する。**

理由:
1. `Protocol` 抽象の境界が極めてきれいで、クラウド固有処理は Protocol 実装と `Ota` にほぼ閉じている（`Application` 本体には漏れていない）。差し替え点が 1 箇所（`InitializeProtocol`）に集約される。
2. AFE/VAD/WakeWord/**デバイス AEC・realtime バージイン**・Opus・表情連動（`llm.emotion`→`SetEmotion`）・MCP デバイス制御を**無改修で再利用**でき、Phase 5（音声バックエンド化）〜Phase 8（バージイン）の工数とリスクを大幅に下げられる。
3. design-spec の API スキーマ（§11）と xiaozhi スキーマ（§5b.4）の差分は backend 側 Adapter（`bot_event_publisher` / WS ルート）で吸収できる。CoreS3 側は xiaozhi の `tts/stt/llm/mcp/listen` を話すクライアントのまま保てる。

ただし以下は案A でも対応が必要:
- `Ota` のクラウド activation を無効化し、NVS `websocket.url`/`token` を **BLE/Setup から backend URL/トークンで埋める**経路を新設（§6.3-C の BLE Wi-Fi 設定機構を拡張）。
- backend に Opus エンコード/デコード（faster-whisper 等への入力は PCM 化）と、xiaozhi 互換の hello/tts/stt/llm/mcp 応答を実装。
- 将来 design-spec の Vision/自発話しかけ等、xiaozhi に存在しないイベントは `mcp`/`custom` または独立 WS（§11.5 commands）で拡張する。

> 段階移行としては「まず案A で backend に接続（クラウド除去 + WS 差し替え）→ 必要に応じて個別機能を自前化」が、CLAUDE.md の「既存を壊さない／段階分離」とも整合する。完全置換（案B）は将来 xiaozhi 依存を切りたくなった時点で再検討すればよい。

---

## 9. リスクと未確認事項

### 9.1 タスク指示書・design-spec との相違（修正提案）

- **`hal_ws_avatar.cpp` の役割**: タスク指示書は「音声認識・LLM 連携の中心」と推測していたが、実体は **M5Stack クラウド経由のアバター遠隔制御・ビデオ通話・カメラ送信用 WebSocket**。LLM/音声認識/Wake Word の中心は **xiaozhi-esp32 の `Application` + `protocols/`**。→ design-spec / 後続 Phase の前提を修正すべき。
- **`hal_ws_avatar.cpp` の規模**: 「約18,000行」とあったが実際は **521行**。巨大ファイルは存在しない（hal 最大は hal_ws_avatar 521行、app_setup が 3,101行）。
- **`hal_ezdata.cpp` の役割**: 「設定保存方式」と推測されていたが、実体は **クラウド MQTT リモート制御**。ローカル設定保存は xiaozhi の NVS `Settings`。→ 設定管理の置換先として転用不可、削除対象。

### 9.2 未確認事項（後続 Phase をブロックし得るもの）

**解消済み（fetch 後の精査で確定）**:

| # | 事項 | 結論 | 根拠 |
|---|---|---|---|
| 1 | xiaozhi `Application` の内部構造・プロトコル結合度 | **解消**。状態機械（§5b.1）・5 タスク音声パイプライン（§5b.2）・`Protocol` 純粋仮想抽象（§5b.3）を精査。クラウド固有処理は Protocol 実装と `Ota` にほぼ閉じ、`Application` は接続先/認証を持たない → **案A（Protocol 差し替え）で温存可能**（§8.1） | `application.cc` / `protocol.h` / `audio_service.cc` |
| 2 | CoreS3 デバイス側 AEC 実用性 | **大きく後退**。AFE+AEC コード経路・バージイン（realtime mode）・参照ch は全て存在。ブロッカーは Kconfig `depends on` への StackChan 追加（1 行）のみ。残るは実機での音響分離検証 | §3.2 / §5b.6 |
| 6 | xiaozhi の OTA/設定取得フロー | **解消**。`api.tenclass.net` がプロビジョニングサーバで、応答が NVS `websocket`/`mqtt` に接続先/トークンを書き込む。WS Protocol はそれを読むだけ → backend では BLE/Setup から NVS を埋める経路で代替可能 | `ota.cc:46-172` |

**未解消（後続 Phase をブロックし得る）**:

| # | 事項 | ブロックする Phase | 理由 |
|---|---|---|---|
| 3 | `secret_logic` 実装の所在（weak スタブのみ） | クラウド削除の影響範囲確定 | 実認証ロジックがビルド時上書きか不明。ただし WS アバター/Account 系（M5 クラウド）専用で、AI 会話（xiaozhi）とは独立。削除対象側 |
| 4 | Wi-Fi 認証情報の NVS 保存先（WifiManager/esp-wifi-connect 管轄） | Phase 1, 3 | Backend URL 等の設定追加・既存設定維持の整合に必要。なお NVS `wifi.ota_url` は OTA URL 上書き用に存在（`ota.cc:46-50`） |
| 5 | ビルド可否 | 全 Phase | 本調査マシンに ESP-IDF 環境がなく `idf.py build` 未実行。`fetch_repos.py` は実行済み（`xiaozhi-esp32/` 展開・パッチ適用済み）が **ビルド未確認** |
| 7 | AEC 有効時の実機音響分離・参照信号品質、バージイン誤検知率 | Phase 8 | コード/Kconfig 上は有効化可能だが、CoreS3 のスピーカー↔マイク物理配置での実用性は実機検証必須 |

> 注: §1-§4・§6・§7 は `firmware/main/` のコミット済みコードと設定に基づく。§5b は `firmware/xiaozhi-esp32/`（fetch_repos 取得・パッチ適用済み）の精査に基づく。
