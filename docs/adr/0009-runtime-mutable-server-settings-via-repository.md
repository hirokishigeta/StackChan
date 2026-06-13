# ADR-0009: サーバー全体の音声(TTS)設定をリポジトリ経由で実行時変更可能にする

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0006（下り TTS に Irodori-TTS を採用）/ ADR-0008（VoiceDesign caption で声色制御）を運用面で補完する

## コンテキスト

設定ダッシュボード（`/dashboard`）から、オーナーが次の 3 領域を編集できるようにする要望が出た:

1. エージェントプロンプト（`BotSettings.agent.system_prompt` ほか） — **デバイス単位**。既存の `PUT /api/settings/{device_id}` で永続化できる。
2. 音声(TTS)プロンプト（`irodori_caption` / `irodori_base_style` / `default_tts_provider`） — これらは現状 `AppSettings`（env 由来）に置かれた**サーバー全体**の値で、デバイス単位ではない。再起動なしで変更を反映したい。
3. その他の `BotSettings`（conversation_turn / speech / vision / attention） — デバイス単位。既存 API で永続化できる。

(2) の音声設定は per-device の `BotSettings` には属さない（声のペルソナは 1 つ）。一方で env だけに置くと、変更のたびに再起動が必要になり、ダッシュボードから編集できない。

## 決定

サーバー全体の実行時可変設定（当面は TTS 音声: provider / caption / base_style）を、**ports に ABC・infrastructure に具象**のリポジトリパターンで永続化する（CLAUDE.md / レイヤー規約に従う）。

- ドメイン VO: `domain/settings/value_objects.py` に `ServerVoiceSettings`（`tts_provider` / `irodori_caption` / `irodori_base_style`、frozen）を追加。
- port: `application/ports/server_settings_repository.py`（`get_voice_override` / `save_voice_override`）。
- 具象: `infrastructure/persistence/sqlite_server_settings_repository.py`。既存 SQLite に **単一行（固定主キー）の JSON** として上書き保存する独立テーブル `server_voice_settings`。
- ユースケース: `application/use_cases/manage_server_settings.py` の `ManageServerSettingsUseCase` が「**実効値 = 永続化された override があればそれ、なければ `AppSettings`/env 既定**」を計算する単一地点。
- port: `application/ports/voice_config_provider.py`（`VoiceConfigProvider.current_voice()`）。`ManageServerSettingsUseCase` が実装する。synthesizer（infrastructure）はユースケースではなくこの port に依存する。
- API: `interfaces/api/server_settings_routes.py` に `GET /api/server-settings` / `PUT /api/server-settings`（Pydantic スキーマ）。未知の `tts_provider` は HTTP 422。
- 反映: `IrodoriTtsSynthesizer` は `VoiceConfigProvider` を任意注入で受け取り、**1 合成ごとに** caption / base_style を読む。よってダッシュボードでの caption/base_style 変更は**再起動なしで次の発話から反映**される。provider（dummy↔irodori）の切り替えは synthesizer の再構築（次回プロセス起動）で反映される（重いエンジンのインスタンス差し替えを実行時に行わない）。

## 検討した選択肢

- A: 音声設定も `BotSettings` に持たせる — 声ペルソナは 1 つでデバイス単位ではないため意味的に不整合。全デバイスに同値を複製する破綻を招く。
- B: env のみ（再起動で反映） — ダッシュボードから編集不可・要望未達。
- C: **専用の server-settings リポジトリ（採用）** — ports+infrastructure の既存規約に乗り、override-over-default を 1 箇所で計算でき、synthesizer は port 依存のまま実行時反映できる。

## 理由

per-device 設定と server-global 設定を明確に分離しつつ、どちらもダッシュボードから永続的に編集できる。override-over-default をユースケースに集約することで API と synthesizer が同じ実効値を見る。synthesizer が port を毎回読むので、重い依存を遅延ロードしたまま（torch 不要で `make check` green）caption 変更を即時反映できる。

## 影響

- 新規: `ServerVoiceSettings` VO / `ServerSettingsRepository`・`VoiceConfigProvider` port / `SqliteServerSettingsRepository` / `ManageServerSettingsUseCase` / `server_settings_routes`。
- 変更: `IrodoriTtsSynthesizer` と TTS registry が `VoiceConfigProvider` を任意で受け取る（未注入時は従来どおり `AppSettings` を読むので既存挙動・テストは不変）。di_container で配線。
- ダッシュボード: `/dashboard` を build なしの静的 HTML + vanilla JS に刷新し、`/api/settings/{device_id}` と `/api/server-settings` を fetch で読み書き。`STACKCHAN_DASHBOARD_DEFAULT_DEVICE_ID` を新設（既定 `cores3-001`）。
- ADR-0006 / ADR-0008 は Superseded にしない（採用エンジン・声色制御手段は不変）。本 ADR は「サーバー全体設定を実行時可変に永続化する方法」を補う。
