# ADR-0026: Hermes ストリーミングでツール実行中ステータスを端末表示する

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0024 (HermesAgent) / ADR-0021 (文単位TTS) / ADR-0025 (発話クリーン化)

## コンテキスト

HermesAgent はツール（Web検索・ファイル・コマンド・コード実行等）を使う。応答が返るまで無反応だと「固まった？」と感じる。StackChan 側でツール使用を把握し、**実行中であることを端末に表示**したい（ツール名も具体的に）。

Hermes の `POST /v1/chat/completions`（`stream: true`）の SSE は、通常の `data: {chat.completion.chunk}` に加え、ツール進捗を `event: hermes.tool.progress` + `data: {tool_name,...}` として**混在**して返す（検証済み）。
端末側は `sentence_start`（テキスト表示のみ・音声フレームを伴わなければ喋らない）で**ファーム変更なし**に任意テキストを表示できる（検証済み）。

## 決定

HermesAgent 経路を**ストリーミング化**し、ツール進捗を端末の表示専用 `sentence_start` で出す。

- `AgentGateway.chat` に任意の `progress_cb: ProgressCallback | None` を追加。非ストリーミングの実装（OpenAICompatible/Dummy/OpenClaw）は無視。
- `HermesAgentGateway`: `progress_cb` 有り時は `OpenAICompatibleGateway.chat_streaming` で SSE を読み、`hermes.tool.progress` を `_tool_label()` で日本語ステータス（例「🔧 Web検索を実行中…」）に変換して `progress_cb` を呼ぶ。content デルタを蓄積し、終了後に従来の構造化パーサで `AgentReply` 化。`progress_cb` 無し時は従来の非ストリーミング。ペルソナ/モデル委譲（system_prompt/model_name を空に）は両経路で維持。
- `bot_audio_ws._run_agent_turn`: `tts.start`＋`speaking` をエージェント呼び出しの**前**に出し、`progress_cb` が**表示専用 `sentence_start`**（音声フレーム無し）で端末にツールステータスを表示。応答後に通常の文単位読み上げ→`tts.stop`。エラー/abort 経路でも `tts.stop`＋状態リセットを保証。
- 同一ラベルの連続送信は抑制（スパム防止）。

## 検討した選択肢

- 選択肢 A（採用）: chat/completions ストリーム＋表示専用 sentence_start。ファーム変更不要、OpenAI互換のまま、ツール名表示可。
- 選択肢 B: `/api/sessions/.../chat/stream`（`event: tool.started` 等のリッチイベント）。情報は多いがセッション管理と非OpenAIなパースが必要で重い。
- 選択肢 C: 新しい `{"type":"status"}` メッセージ＋ファーム表示ハンドラ。要フラッシュでリスク増。

## 影響

- ツール使用中、端末に「🔧 …実行中…」が表示され、終わると通常応答に置き換わる。`tts.start` がエージェント呼び出し前に出るため、思考中も Speaking 状態（メッセージ列は `stt → tts.start → wake → llm → sentence_start → audio → tts.stop`、既存テストも更新）。
- フォローアップ: ツール名→ラベルの網羅性向上、`tool.started/completed` の活用、ダッシュボードでのツール実行ログ可視化。
