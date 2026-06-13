# ADR-0008: Irodori-TTS は VoiceDesign(v3) チェックポイント + caption で声色を制御する

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0006（下り TTS に Irodori-TTS を採用）を**詳細化（refine）**する。ADR-0006 の port/registry/emoji 制御の決定はそのまま有効

## コンテキスト

ADR-0006 で下り TTS に Irodori-TTS（`Aratako/Irodori-TTS-500M`）を採用し、`emotion`→絵文字スタイル制御＋参照 wav によるゼロショット話者指定を方針とした。

実機向けに声色を「明るいが静かめの少女の声。少し高めで、親しみやすく、楽しそう」に固定したいというオーナー要望が出た。Ubuntu(RTX 3090) 上で実モデルを検証した結果、以下が判明した:

- `Aratako/Irodori-TTS-500M`（v1）は `latent_dim=128` で、現行コードが既定で使う codec `Aratako/Semantic-DACVAE-Japanese-32dim`（32dim）と**次元不一致でロード不可**（`Latent dimension mismatch: checkpoint latent_dim=128 but codec latent_dim=32`）。
- リポジトリ `main` は **v3** 系（`Irodori-TTS-500M-v3` / `Irodori-TTS-600M-v3-VoiceDesign`）向けで、released v2/v3 は 32dim codec を使う。
- **VoiceDesign** 系（`Irodori-TTS-600M-v3-VoiceDesign`）は `use_caption_condition=True` で、**caption（声の自然言語記述）による声色指定 + 参照 wav なし（no_ref）合成**が可能。検証で caption のみ・no_ref で 48kHz 音声を生成できることを確認した。

## 決定

声色固定の要望を満たすため、Irodori-TTS の構成を次に確定する:

- チェックポイント: **`Aratako/Irodori-TTS-600M-v3-VoiceDesign`**（caption 駆動の VoiceDesign / v3）
- codec: **`Aratako/Semantic-DACVAE-Japanese-32dim`**（32dim、チェックポイントと次元一致）
- 声色は **caption**（`STACKCHAN_IRODORI_CAPTION`、既定「明るいが静かめの少女の声。少し高めで、親しみやすく、楽しそうに話してください。」）で指定し、参照 wav 未設定時は **`no_ref=True`** で合成する
- `emotion`→絵文字制御（ADR-0006）は**そのまま併用**し、声色の上に瞬間的な表情を載せる。常時付与する persona base emoji（旧既定 `😏`）は**既定で無効（空）**にし、声色は caption に一任する（`STACKCHAN_IRODORI_BASE_STYLE` で再有効化可）
- `STACKCHAN_IRODORI_MODEL_PATH` は **ローカルパスまたは HF repo id** を受け付け、repo id の場合は `hf_hub_download(repo_id, "model.safetensors")` で解決（キャッシュ）する

## 検討した選択肢

- A: v1 `Irodori-TTS-500M` + 128dim codec — 旧コードの想定。声色固定は参照 wav クローン頼みで、自然言語での声色指定ができない。v3 系より古い
- B: v3 `Irodori-TTS-500M-v3` + 参照 wav — caption 非対応。声色は参照音声アセットの用意が前提になり、要望の「言葉で声色を指示」と噛み合わない
- C: **`Irodori-TTS-600M-v3-VoiceDesign` + caption（採用）** — 自然言語の caption で声色を直接指定でき、参照 wav アセット不要（no_ref）。オーナー要望に最も合致

## 理由

オーナー要望は「言葉で声色を固定する」ことであり、それを満たすのは caption 対応の VoiceDesign 系だけ。32dim codec とペアで次元一致しロード可能なことを実機（CUDA）で検証済み。ADR-0006 の port/registry/emoji 設計はそのまま活き、本 ADR はチェックポイントと声色制御手段を具体化するに留まる。

## 影響

- 既定設定を更新: `STACKCHAN_IRODORI_CAPTION` 新設（声色プロンプト）、`irodori_base_style` 既定を空に変更、`STACKCHAN_IRODORI_MODEL_PATH` に HF repo id 解決を追加
- 運用（Ubuntu）: `STACKCHAN_DEFAULT_TTS_PROVIDER=irodori`, `STACKCHAN_IRODORI_MODEL_PATH=Aratako/Irodori-TTS-600M-v3-VoiceDesign`, `STACKCHAN_IRODORI_DEVICE=cuda`, `STACKCHAN_IRODORI_CODEC_DEVICE=cuda`, `STACKCHAN_AUDIO_ENCODER=opus`
- ADR-0006 は Superseded にはしない（採用エンジン・抽象設計は不変）。本 ADR は「どのチェックポイントで、どう声色を決めるか」を補う
