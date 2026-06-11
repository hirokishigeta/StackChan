# ADR-0001: CoreS3 を入出力端末とし AI 処理を PC バックエンドへ集約する

- Status: Accepted
- Date: 2026-06-12
- 関連: docs/design-spec.md

## コンテキスト

現行の StackChan ファームウェアは、AI 処理（音声認識・LLM・Wake Word）を外部クラウド API（XiaoZhi 等）に依存している。モデル・Prompt・エージェントの差し替え自由度が低く、設定変更の自由度も限られる。手元のノート PC で任意の LLM / Agent / 音声認識 / 画像認識モデルを動かし、StackChan をその身体として使いたい。

## 決定

- CoreS3（firmware）は音声入出力・カメラ・画面/表情表示・簡易制御に責務を限定した「AI に身体を与える入出力端末」とする
- LLM / Agent / 音声認識 / 画像認識 / Wake Word 管理 / 設定管理は PC 上の Python (FastAPI) バックエンドに集約する
- Agent バックエンドは AgentGateway 抽象で差し替え可能にする（HermesAgent / OpenClaw / OpenAI 互換 API / Codex）
- 設定変更は Web ダッシュボード（ブラウザ）から行い、CoreS3 側には Wi-Fi / Backend URL / Device ID / 画面系基本設定のみ持たせる

## 検討した選択肢

- A: CoreS3 単体で完結（オンデバイス推論）— ESP32-S3 のメモリ・演算能力では大型モデルが動かず、自由度がない
- B: クラウド API 依存を継続 — モデル差し替え・ローカルモデル利用・プライバシー面で制約が残る
- C: PC バックエンド集約（採用）— モデル自由度・拡張性が最大。LAN 内前提のため遅延も許容範囲

## 理由

拡張性（モデル・Agent の差し替え）と保守性（AI 処理の責務を 1 箇所に集約）を最優先とした。CoreS3 のハードウェア制約（PSRAM 8MB）では選択肢 A は成立しない。

## 影響

- firmware は段階的な責務分離リファクタリングが必要（design-spec Phase 1）
- PC バックエンド未起動時・Wi-Fi 切断時のフォールバック動作を firmware 側に実装する必要がある
- バージイン対応のため音声通信は WebSocket ストリーミングが基本となる（design-spec §7）
