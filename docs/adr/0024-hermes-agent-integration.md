# ADR-0024: HermesAgent (NousResearch hermes-agent) を OpenAI互換で本接続する

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0004 (xiaozhi protocol) / design-spec §11 / #6

## コンテキスト

`HermesAgentGateway` は固定文を返すスタブだった。NousResearch の hermes-agent を実際のエージェントバックエンドとして使えるようにしたい。要件: HermesAgent 選択時はエージェント設定（ペルソナ/モデル/メモリ/スキル）を Hermes に委譲し、こちら側で設定できる部分（音声/ターン取り/ウェイク等）は引き続き設定可能にする。加えてダッシュボードに「Hermes を開く」ボタンを置く。

調査結果（公式ドキュメント）:
- hermes-agent は **OpenAI互換 API サーバ**を持つ（既定 `http://127.0.0.1:8642/v1`、`POST /v1/chat/completions`、Bearer `API_SERVER_KEY`、streaming 対応）。
- メモリ（FTS5 recall）、スキル自己生成、cron スケジューラ、MCP、サブエージェントを内蔵。サーバー側会話状態は `/v1/responses`（`store`/`previous_response_id`）でも提供。
- **専用 Web UI/ダッシュボードは無い**（TUI/CLI。外部UIがクライアントとして接続する設計）。

## 決定

`HermesAgentGateway` を OpenAI互換トランスポートで実装する（`OpenAICompatibleGateway` を内部委譲）。

- 接続情報は設定から: `hermes_base_url` / `hermes_api_key` / `hermes_model`（ハードコード禁止・CLAUDE.md）。
- **委譲**: Hermes 選択時は呼び出し前に profile の `system_prompt` と `model_name` を空にする。ペルソナとモデルは Hermes 側が所有（こちらの per-device 設定を送らない）。
- emotion 取得のため応答フォーマット指示は維持し、Hermes が JSON で返さなければプレーンテキスト→neutral にフォールバック。
- ダッシュボードの「Hermes を開く」ボタンは、Hermes に Web UI が無いため**設定可能な URL** (`hermes_dashboard_url`、例: Open WebUI) を開く方式（空なら無効）。

## 検討した選択肢

- 選択肢 A（採用）: `/v1/chat/completions` で本接続、persona/model を委譲。確実・既存パーサ流用・テスト容易。
- 選択肢 B: 最初から `/v1/responses` + `previous_response_id` で Hermes 管理メモリを使う。会話状態を WS セッション層から通す必要があり、本 PR では見送り（下記フォローアップ）。
- 選択肢 C: スタブのまま。要件未達。

## 影響

- HermesAgent が実際のブレインとして動作（env で `STACKCHAN_DEFAULT_AGENT_TYPE=HermesAgent` + `STACKCHAN_HERMES_*`）。
- emotion は Hermes が JSON 準拠しなければ neutral 固定（表情表現は弱まる）。
- フォローアップ(別PR): (1) ダッシュボードに Hermes 設定 UI と「開く」ボタン、agent設定の委譲時グレーアウト、(2) `/v1/responses`・`/api/sessions` による Hermes 管理メモリ、`/api/jobs` でのリマインダ連携、(3) emotion マッピング強化。
- API キーは `.env` 管理（リポジトリに含めない）。
