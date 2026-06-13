# ADR-0010: ファーム側で TTS 音声出力を先行有効化し、サーバ起点の listen stop を受理する

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0004（xiaozhi Protocol 再利用）, ADR-0008（VoiceDesign 声色）, design-spec §7（会話ターン）, PR #45（backend 会話ターン処理）

## コンテキスト

実機検証で、下り TTS 再生に2つのデバイス側欠陥が判明した。

1. **頭欠け**: サーバが `tts.start` → Opus 音声を送ると、返答の冒頭（例「こんにちは」が「ちは」から）が再生されない。原因は xiaozhi-esp32 の `AudioOutputTask` が**最初のデコード済みフレーム到着時に初めて**出力コーデックを有効化する遅延ロードで、AW88298 アンプ/I2S が温まる前に先頭フレームが鳴ること（`main/audio/audio_service.cc` AudioOutputTask、`main/boards/m5stack-core-s3/cores3_audio_codec.cc` EnableOutput）。
2. **プツプツ（アンダーラン）**: 再生キュー `MAX_PLAYBACK_TASKS_IN_QUEUE=2`(=120ms) が浅く、ネットワークジッタで枯れる。

当初はバックエンドで無音リードイン（300〜800ms）を前置する回避策を入れたが、根本はデバイス側であり、オーナー方針で**ファーム根治＋回避策撤去**とした。

加えて、会話終了時に端末の auto 再リッスンを止める手段が WS プロトコルに無かった（`tts.stop` 後 auto モードは自動で再リッスン、`application.cc`）。

## 決定

xiaozhi-esp32 を `patches/xiaozhi-esp32.patch` 経由で次のように改修する（外部 upstream は patch で管理。ADR-0004）。

1. **頭欠け根治**: `Application::HandleStateChangedEvent()` の Speaking 遷移（=tts.start）で `AudioService::PreEnableOutput()` を呼び、出力コーデック/アンプを**先行有効化**する。`PreEnableOutput()` は AudioOutputTask と同じ enable 経路を冪等に実行（`codec_->output_enabled()` ガード）。`ResetDecoder()` と出力の無効化（タイムアウトでの電源OFF）経路は不変。
2. **プツプツ根治**: `MAX_PLAYBACK_TASKS_IN_QUEUE` を 2→8（約480ms）に拡大し、ジッタを吸収。
3. **サーバ起点 listen stop**: `OnIncomingJson` に `type=="listen"` を追加し、`{"type":"listen","state":"stop"}` 受信で `SetDeviceState(kDeviceStateIdle)`。バックエンドが会話終了時に送出（PR #45）し、auto 再リッスンを止めて待機へ戻す。

バックエンド側の無音リードイン回避策は撤去（PR #45）。下りのリアルタイム・ペーシング（ジッタバッファ溢れ防止＋half-duplexゲート維持）は維持する。ファームのバージョンを 1.5.0→1.5.1（音声修正）に上げる。

## 検討した選択肢

- A: バックエンドの無音リードインのまま — リフラッシュ不要だが対症療法で、立ち上げ遅延ぶん遅延が増え、端末差で破綻。声色プロンプト等と同様に「言葉/設計で根治」する方針に反する
- B（採用）: ファームで出力を先行有効化＋バッファ拡大＋サーバ listen stop — 根治。再書き込みが必要だが既に patch 運用＋ビルド環境あり

## 影響

- `patches/xiaozhi-esp32.patch` を更新（3点）。`idf.py build` 成功を確認（stack-chan.bin 生成、app 32% 余裕）。ホストテスト緑。
- 反映には端末の再ビルド＆書き込み（`idf.py build flash`）が必要。
- backend は無音リードイン設定/コードを撤去（PR #45）し、会話終了で `listen stop` を送る。
- clang-format: 当マシンには pip wheel 版があるが、vendored upstream 全体の再フォーマットは不適切なため変更行のみ既存スタイルに手動準拠（whole-file 整形は不採用）。
