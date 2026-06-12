# ADR-0006: 下り TTS エンジンに Irodori-TTS を採用する

- Status: Accepted
- Date: 2026-06-12
- 関連: ADR-0004, docs/backend-protocol.md（#7-b）, Issue #7, design-spec §11.8

## コンテキスト

backend-protocol.md / ADR-0004 で確定した WS 契約のうち、下り（backend→firmware）の TTS 音声送出（#7-b）には音声合成エンジンの選定が必要だった。backend には現状 TTS（SpeechSynthesizer）port が存在しない（ASR/Vision/WakeWord/Agent/Settings/EventPublisher のみ）。オーナーが TTS エンジンとして Irodori-TTS を指定した（参考: https://zenn.dev/kun432/scraps/87d7776909e4d9 ）。

## 決定

下り TTS エンジンに **Irodori-TTS**（Aratako/Irodori-TTS-500M）を採用する。

- backend に **SpeechSynthesizer port（ABC）** を新設し、Irodori-TTS を具象 Adapter として実装する
- 他の port と同様、**依存（PyTorch / HF チェックポイント等）は optional + 遅延ロード**とし、`make check` は重い依存・実モデルなしで通す（テストは fake）
- provider は registry 方式で解決し差し替え可能にする（将来 別 TTS へ swap 可能）
- AgentGateway が返す `emotion` を Irodori-TTS の**絵文字スタイル制御**へマッピングする
- 出力 48kHz を WS 下り音声パラメータ（既定 Opus 24kHz/60ms）へ**リサンプル → Opus エンコード**して送出する
- 話者は参照 wav によるゼロショット指定。参照音声のパスは設定（config）化し、実際の音声アセット選定は別途（TODO）

## 検討した選択肢

- A: Irodori-TTS（採用）— 日本語特化、MIT で商用可、絵文字による感情・スタイル制御が本プロジェクトの emotion/表情制御と整合、ゼロショットクローンで話者を柔軟に。一方 拡散ベースで重く（~7.7GB VRAM）、漢字読み精度が同規模比やや低く、リアルタイム性は実機・GPU 依存
- B: クラウド TTS（OpenAI/Google/Azure 等）— 低レイテンシだが外部依存・課金・プライバシー、LAN ローカル前提（design-spec §13）と相性が悪い
- C: 軽量ローカル TTS（VOICEVOX / piper 等）— 軽快だが、オーナー指定は Irodori-TTS

## 理由

オーナー指定であること、MIT で商用可、日本語特化、emotion→絵文字制御が既存設計と噛み合うこと。port 抽象＋registry で実装するため、リアルタイム性や読み精度が実機で問題になった場合も Adapter 差し替えで対応でき、選定リスクを吸収できる。

## 影響

- backend に SpeechSynthesizer port + Irodori Adapter + Opus encoder + 48k→24k リサンプル経路を新設（#7-b）
- WS サーバの `tts.start → (音声フレーム) → tts.stop` 区間に下り Opus フレーム送出を実装
- 重い依存は optional extra（例: `[tts]`）。実運用は GPU 推奨。レイテンシ・読み精度・話者アセットは実機検証事項（別途）
- design-spec / backend-protocol.md の #7-b 記述を本決定に合わせて更新する
