# ADR-0013: ダッシュボードからのリファレンス音声生成エンドポイント

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0006（Irodori-TTS）/ ADR-0008（VoiceDesign caption persona）/ ADR-0009（runtime-mutable server settings）/ ADR-0012（声サンプルピッカー）/ docs/design-spec.md §11

## コンテキスト

ADR-0012 で「事前生成された wav 群をディレクトリから列挙し、選択した wav をリファレンスにクローンする」声サンプルピッカーを導入した。当時はサンプル wav を「別途 GPU ホストで生成しておく」前提で、バックエンドでの逐次生成は選択肢 C として「GPU 必須・責務分離に反する」と退けていた。

しかし運用上、ユーザーがダッシュボード上で caption と例文を入力し、その場で 1 つの綺麗なリファレンス声を作って一覧に追加できると体験が大きく良くなる。実際の生成は GPU ホスト（バックエンドが Irodori-TTS の重い依存を入れて動く環境）で行われ、CPU/テスト環境では engine が無いので利用不可（503）でよい、という前提なら責務分離とも矛盾しない。

通常合成（per-turn の `synthesize`）の本番ポリシーは「選択リファレンスを caption 無しでクローン」だが、リファレンス生成はその逆で「リファレンス無し（`no_ref`）+ 明示 caption + seed」で新しい声をミントする必要がある。

## 決定

- `SpeechSynthesizer` ポートに `generate_reference(*, text, caption, seed=None) -> SynthesizedAudio` を追加する。`@abstractmethod` にはせず、既定実装は `SpeechSynthesisError("reference generation not supported")` を送出する。これで caption 非対応エンジン（dummy）やテスト用 fake は実装不要。
- `IrodoriTtsSynthesizer.generate_reference` は runtime を `no_ref=True` / 明示 caption / `num_candidates=1` / `decode_mode="sequential"` / 高品質な `num_steps`（新設定 `irodori_generation_num_steps` 既定 64）/ seed（既定 `irodori_seed`）で 1 回走らせる。重い依存は遅延ロードのまま。
- `VoiceSampleRepository` に `save(*, sample_id, pcm, sample_rate, label=None, caption=None) -> VoiceSample` を追加。`FilesystemVoiceSampleRepository` は `<sample_id>.wav`（mono PCM16）をサンプルディレクトリに書き、`samples.json` に label/caption をマージ記録する（他エントリは保持）。
- sample_id は安全なスラッグ（`[A-Za-z0-9_-]+`）のみ許可。区切り文字やトラバーサルは `InvalidSampleIdError`。既存 id への上書きは行わず `DuplicateSampleError`（API では 409）。上書き不可を採用した（誤操作で既存声を壊さない）。
- `POST /api/voice-samples`（body: `{id, label?, caption(必須・非空), text(既定=プロジェクト例文)}`）を追加。ユースケース `GenerateVoiceSampleUseCase`（application/use_cases）が `generate_reference` -> `save` を実行し `{id, label}` を返す。HTTP マッピング: 不正スラッグ / 空 caption -> 422、重複 id -> 409、合成不可（`SpeechSynthesisError`）-> 503。ビジネスロジックはユースケースに置き、ルートは変換のみ。
- ダッシュボードの「音声 (TTS)」パネルに「ref生成」カードを追加（label / caption / 例文の入力 + 生成ボタン）。生成は遅いのでボタンを無効化しトーストを出し、完了後に一覧を再取得して新サンプルを選択状態にする。

## 検討した選択肢

- 選択肢 A（採用）: バックエンドに生成エンドポイントを追加し、GPU ホストでのみ実際に動作（他環境は 503）。ADR-0012 の選択肢 C を、手動・一回限りの生成フローに限って見直す。
- 選択肢 B: 生成は引き続き GPU ホスト上の別スクリプトで行い、ダッシュボードからは扱わない。体験が悪い（ファイル直置きが必要）。

## 理由

A は ADR-0012 の資産（ファイルシステムリポジトリ・ピッカー UI・設定フロー）をそのまま拡張でき、追加の常駐サービスを要さない。重い生成は GPU ホストにとどまり、CPU/テスト環境では 503 を返すだけなので design-spec §2.1 の役割分担と矛盾しない。ポートの既定実装で fake/dummy を壊さずに済む。

## 影響

- 実際の生成は GPU ホスト（`[tts]` extra + モデル）でのみ成功する。テストは torch/GPU を要求しない（fake runtime と小さな PCM をモックする）。
- `samples.json` は生成のたびにマージ更新される（既存の手置きエントリは保持）。
- ADR-0012 の選択肢 C の評価は、本 ADR の範囲（手動一回限りの生成）に限って見直された。per-turn 合成は引き続きバックエンドで重い推論を常時行わない方針のまま。
