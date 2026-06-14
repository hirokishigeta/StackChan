# ADR-0022: opus デコードタスクの優先度を上げて再生クラックルを解消

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0010 (firmware audio) / ADR-0021 (文単位TTS) / #67 (再生バッファ8→16)

## コンテキスト

長文・通常返答ともに、TTS再生で「プツプツ」（特に喋り始め）が残っていた。backend側の対策（文単位ストリーミング ADR-0021、prime バースト、ws-ping 延長）でも解消しきれなかった。

firmware の `AudioService` を調査した結果、FreeRTOS タスク優先度が:

- `audio_input`（マイク入力/常時リッスン）= **8**（高、コア0ピン留め）
- `audio_output`（I2S出力）= **4**
- `opus_codec`（デコード: decode_queue → playback_queue）= **2**（最低クラス）

`AudioOutputTask` は playback_queue にフレームが1つ入った瞬間に再生を開始する（最小バッファ閾値なし）。デコードタスクが優先度2で、常時走る入力タスク(8)に恒常的にプリエンプトされるため、再生中に **decode が playback の消費に追いつかず playback_queue が枯渇 → I2S アンダーラン → プツプツ**。喋り始めに多いのは開始直後にバッファの貯金が無いため。

## 決定

`opus_codec` タスクの優先度を **2 → 6** に上げる。

- 出力タスク(4)より高くすることで、出力がキューを消費する前にデコード済みPCMが常に用意される。
- 入力キャプチャ(8)より低く保ち、入力のレイテンシは犠牲にしない。

あわせて、vendored xiaozhi ツリーへの変更を管理する `patches/xiaozhi-esp32.patch` を現ツリーから再生成した。これにより **PR #71 で patch へ反映漏れしていたタップ機能 `Application::ReturnToWakeWaiting`** も初めて patch に取り込まれ、リポジトリからのクリーンビルド（`fetch_repos.py` + `git apply`）が再び成立する。

## 検討した選択肢

- 選択肢 A（採用）: デコードタスク優先度を 6 に。低リスク・低コスト・原因に直接対応。
- 選択肢 B: `AudioOutputTask` に最小バッファ閾値（数フレーム貯まるまで再生開始しない）を実装。効果はあるがロジック追加でリスク増。将来併用可。
- 選択肢 C: 発話中にデバイス側の常時リッスン処理(AFE/wakenet)を完全停止して入力タスク負荷を下げる。backend-wake では理にかなうが、状態遷移に踏み込むためリスク中。次段の候補。

## 影響

- xiaozhi(vendored)への変更のため、`patches/xiaozhi-esp32.patch` の更新で管理（gitignore 対象ツリー）。`firmware/xiaozhi-esp32/` 直下の編集は `git add` されない点に注意。**xiaozhi を編集したら必ず `git -C firmware/xiaozhi-esp32 diff > firmware/patches/xiaozhi-esp32.patch` で patch を更新すること。**
- ESP-IDF v5.5.4 でビルド成功・実機フラッシュ済み（1.6.4）。
- まだ残る場合は選択肢 B / C を検討。
