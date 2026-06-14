# ADR-0023: backend-wake では発話中のデバイス wakenet を無効化する

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0015 (firmware backend-wake) / ADR-0022 (decode 優先度) / ADR-0014 (backend wake gate)

## コンテキスト

backend-wake 構成（ウェイク検出は PC バックエンド側）にもかかわらず、再生中に次の2症状が残っていた:

- **発話が突然止まり「ふよっ」(popup) が鳴る**: シリアルログで原因確定 —
  ```
  391911 listening -> speaking
  395951 << それでは少しだけお話ししてみますね。
  397711 Wake word detected: Hi,Stack Chan (state: 6)
  397711 Abort speaking
  397711 speaking -> listening
  ```
  デバイス側 AFE wakenet（"Hi,Stack Chan"）が、AEC が無いためボット自身の TTS 音声をウェイク語と**誤検出**し `AbortSpeaking` を発火していた。
- **プツプツ（再生クラックル）**: wakenet は高優先度の `audio_input` タスク(8)で `wake_word_->Feed()` され、優先度を上げた opus デコード(6)を再びプリエンプトして再生キューを枯渇させていた。

`Application::OnStateChanged` の Speaking 遷移で `EnableWakeWordDetection(IsAfeWakeWord())` が呼ばれており（上流の「発話中バージイン」用）、これが両症状の共通元凶だった。listening では既定で wakenet は無効（`CONFIG_WAKE_WORD_DETECTION_IN_LISTENING` 未定義）だが、speaking でだけ有効化されていた。

## 決定

backend-wake ビルド（`CONFIG_STACKCHAN_BACKEND_WAKE`）では、Speaking 遷移で **`EnableWakeWordDetection(false)`** とし、発話中のデバイス wakenet を完全に無効化する。従来ビルドは `IsAfeWakeWord()` のまま（挙動不変）。

ウェイク検出は完全にバックエンド側（ADR-0014）なので、デバイス wakenet は backend-wake では不要かつ有害。

## 検討した選択肢

- 選択肢 A（採用）: 発話中の wakenet を backend-wake で無効化。誤Abortとプツプツ（CPU競合）の両方を同時に解消、最小変更。
- 選択肢 B: AEC を有効化して誤検出を抑える。CoreS3 では AEC が重く、CPU 競合（プツプツ）を悪化させるため不可。
- 選択肢 C: 再生バッファ／優先度のさらなる調整のみ。誤Abortは直らず、対症療法。

## 影響

- backend-wake では発話中にデバイス側ウェイクでのバージイン（割り込み）はできなくなる。会話の中断は画面タップ（ADR-0020）／終了ワード／idle で行う。
- vendored xiaozhi への変更のため `patches/xiaozhi-esp32.patch` を更新（[[firmware-xiaozhi-patch-workflow]] 参照）。
- ESP-IDF v5.5.4 でビルド・フラッシュ済み（1.6.5）。プツプツ・発音停止の改善を実機で確認すること。
