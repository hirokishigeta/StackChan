# ADR-0019: NeMo Parakeet (CTC) を sherpa-onnx ランタイム上の日本語 ASR モデルに採用

- Status: Accepted
- Date: 2026-06-14
- 関連: docs/backend-protocol.md §3.2 / ADR-0014（wake word gate）/ backend/app/infrastructure/speech/

## コンテキスト

backend の音声認識（ASR）は sherpa-onnx の `OfflineRecognizer.from_transducer(...)`
で Zipformer transducer モデルをロードしている。日本語の認識精度が十分でなく、
固有名詞や口語表現で誤認識が目立つ。

より高精度な日本語モデルとして
`sherpa-onnx-nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8`（NeMo Parakeet CTC）が
利用できる。これは **同じ sherpa-onnx ランタイム** で動作し、Whisper や新しい重い
依存を追加せずにロードできる（`OfflineRecognizer.from_nemo_ctc(model=..., tokens=...)`）。

## 決定

既存の `SherpaOnnxSpeechRecognizer`（provider `sherpa-onnx`）の遅延ロード部分に
NeMo-CTC のモデルローダ分岐を追加する。

- `sherpa_nemo_model_path` が設定されていれば `from_nemo_ctc(model=..., tokens=...,
  num_threads=..., debug=False)` でロードする。
- 未設定なら従来どおり `from_transducer(...)` をロードする（後方互換）。
- どちらの構成も無効なら従来と同じ `SherpaOnnxConfigError` を送出する。
- `recognize()` の波形変換 / デコード経路はモデル種別に依存せず共通のまま。

これは **新しい provider ではなく同一 provider の別ローダ**であるため、registry に
provider 分岐（if）は追加しない（CLAUDE.md: provider 分岐を増やさない）。

モデルファイルは GPU/ホスト側で人間がダウンロードし、
`STACKCHAN_SHERPA_NEMO_MODEL_PATH` + `STACKCHAN_SHERPA_TOKENS_PATH` で渡す
（ハードコード禁止）。

## 検討した選択肢

- A: 同一 sherpa-onnx アダプタに NeMo-CTC ローダ分岐を追加（採用）。
  - メリット: 新依存なし、registry 無変更、後方互換、遅延ロード維持。
  - デメリット: アダプタ内に小さなモデル種別分岐が増える。
- B: 新 provider クラス（`SherpaNemoSpeechRecognizer`）+ registry 登録。
  - メリット: クラスが純粋。
  - デメリット: ランタイム・波形経路がほぼ同一でコード重複。registry エントリ増。
- C: Whisper など別ランタイム導入。
  - デメリット: 重い依存追加。今回の目的（同一ランタイムで精度向上）に反する。

## 理由

NeMo-CTC は transducer と同じ sherpa-onnx ランタイム・同じデコード経路で動くため、
差分はモデルローダの選択だけ。これは provider の追加ではなくモデル種別の切替なので、
アダプタ内の構成分岐で表現するのが最小かつ凝集的。重い依存を増やさず、`make check`
は sherpa-onnx 未インストールでも遅延 import により green を維持する。

## 影響

- 設定に `sherpa_nemo_model_path`（既定空）を追加。`sherpa_num_threads` の既定を
  2 に引き上げ（CTC 推論のスループット）。transducer 設定は維持。
- transducer のみ設定時の挙動は不変（後方互換）。
- フォローアップ: ホスト側でモデルを配置し
  `STACKCHAN_SHERPA_NEMO_MODEL_PATH` / `STACKCHAN_SHERPA_TOKENS_PATH` を設定して
  実機精度を確認する。
