# ADR-0012: 声サンプルピッカー（リファレンス音声クローンで音色を固定）

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0006（Irodori-TTS）/ ADR-0008（VoiceDesign caption persona）/ ADR-0009（runtime-mutable server settings）/ docs/design-spec.md §11

## コンテキスト

Irodori-TTS VoiceDesign は caption（言葉による声色指示）で発話するが、リファレンス wav が無い `no_ref` のままだと、固定 seed を入れても音色が完全には安定しない。確実に音色を固定するには「特定の wav をリファレンスとしてゼロショットクローンする」のが最も確実である。

そこで、あらかじめ GPU ホストで生成しておいた複数の音声サンプル（wav 群）をダッシュボードに一覧表示し、ユーザーが 1 つ選ぶと、その wav をリファレンスとしてクローンするようにしたい。選択状態は ADR-0009 の runtime-mutable サーバー音声設定として永続化し、再起動なしで次の発話から反映する。

## 決定

- サンプル wav 群を置くディレクトリを新設定 `STACKCHAN_VOICE_SAMPLES_DIR`（既定 `~/.stackchan/voice_samples`、`expanduser`）で指定する。ハードコードしない（CLAUDE.md）。
- 1 wav = 1 選択可能な声。サンプル id は wav のファイル名 stem。ラベルは stem を既定とし、任意のサイドカー `<stem>.txt`（1 行目）または `samples.json`（`id -> label` / `id -> {"label"|"caption"}`）があれば上書きする。メタデータは任意・無くてよい。
- ポート `VoiceSampleRepository`（ABC, application/ports）と具象 `FilesystemVoiceSampleRepository`（infrastructure/persistence）を新設する。listing と id→wav パス解決のみを担う。
- `ServerVoiceSettings` に `voice_sample_id: str | None` を追加し、ADR-0009 の既存リポジトリで永続化する（欠損は `None`、後方互換）。GET/PUT `/api/server-settings` のスキーマに露出。未知の id を PUT したら 422。
- 実効リファレンス wav の優先順位: 選択サンプルの wav → `irodori_reference_wav_path` → `None`(`no_ref`)。`IrodoriTtsSynthesizer` は `VoiceConfigProvider.selected_reference_wav()` を介して毎発話で解決する（重い依存は遅延ロードのまま）。
- 一覧 + 試聴 API: `GET /api/voice-samples` -> `[{id, label}]`、`GET /api/voice-samples/{id}/audio` -> wav（`audio/wav`, `FileResponse`）。未知 id は 404。パストラバーサルはサンプルディレクトリ内に解決を限定して防ぐ。
- ダッシュボードの「音声 (TTS)」パネルにサンプル一覧（ラジオ + ▶ 試聴）を追加し、選択 + 保存で `voice_sample_id` を PUT する。

## 検討した選択肢

- 選択肢 A（採用）: 事前生成 wav をディレクトリから列挙し、選択 id をリファレンスにクローン。音色が確実に固定でき、生成は GPU ホストにオフロードできる。
- 選択肢 B: caption + 固定 seed のみで音色固定。実装は軽いが、音色のドリフトを完全には抑えられない。
- 選択肢 C: バックエンドで wav をその場生成して保存。GPU 必須でバックエンドが重くなり、責務分離（design-spec §2.1）に反する。

## 理由

A は音色の再現性が最も高く、重い生成処理を GPU ホストへ分離できる。既存の ADR-0009 設定フロー・ADR-0006 シンセサイザにそのまま拡張でき、追加依存も無い（ファイルシステムのみ）。

## 影響

- 実際のサンプル wav は別途 GPU ホストで `STACKCHAN_VOICE_SAMPLES_DIR` に生成する。バックエンド単体ではディレクトリが空でも動作（一覧は空、選択なし）。
- `ManageServerSettingsUseCase` のコンストラクタが `VoiceSampleRepository` を要求するよう変更（DI とテストを更新）。
- 選択中サンプルが後で削除された場合、`selected_reference_wav()` は `None` を返し、次のフォールバックで合成を続行する（発話を落とさない）。
