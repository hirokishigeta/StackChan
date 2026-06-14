# ADR-0015: ファームを完全バックエンドwake（常時リッスン）にする

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0014（バックエンド wake-word gate）, ADR-0004（xiaozhi Protocol 再利用）, ADR-0011（複数ウェイクワード）, design-spec §6/§7

## コンテキスト

ウェイクワードを「任意の日本語」で設定したいというオーナー要望。on-device の esp-sr wakenet は学習済みモデル固定（現在 "Hi StackChan"）で、任意日本語は不可。MultiNet も CN/EN のみ。

そこで wake 検出をバックエンドへ移す方針を決定（オーナー選択: 完全バックエンド検出、"Hi〜" 廃止）。バックエンド側 gate は ADR-0014 で実装済み（STT テキストに設定ウェイクワードが含まれたらエンゲージ）。これを活かすには端末が**常時音声をストリーム**する必要がある。

## 決定

xiaozhi-esp32 を patch で改修し、**完全バックエンドwake（常時リッスン）**にする。ビルド時フラグ `CONFIG_STACKCHAN_BACKEND_WAKE`（firmware/CMakeLists.txt の `add_definitions`）で切替可能（コメントアウトで従来の on-device "Hi StackChan" wake に戻る）。

- `Application::HandleStateChangedEvent` の `kDeviceStateIdle` 分岐で、フラグ有効時は wakenet を待たず**自動でリッスン開始**（`ToggleChatState` の idle 経路を再利用: 未接続なら接続→`SetListeningMode(GetDefaultListeningMode())`）。
- 既定リッスンモードは AutoStop（AEC off）。端末の VAD が発話の区切りで停止 → idle → 上記で**自動再リッスン**。結果、音声は主に発話中に送られ（省電力面も配慮）、バックエンドが VAD→STT→wake-gate(ADR-0014) でエンゲージ判定する。
- 非ウェイク発話はバックエンドが無視（tts.stop を返すが端末は listening のため no-op）。
- バージョン 1.5.4 → **1.6.0**（機能追加）。

## 検討した選択肢

- A: 別の英語 wakenet に差し替え — 任意日本語にならない
- B: MultiNet カスタム — CN/EN のみ、日本語実用外
- C（採用）: 端末常時リッスン + バックエンド検出 — 任意日本語が即機能、重い処理は PC（プロジェクト方針に合致）。電力は USB 給電前提で許容、AutoStop VAD で緩和
- D: 純粋24時間ストリーム — Cより省電力性が劣るため不採用

## 影響

- `patches/xiaozhi-esp32.patch` 更新（idle 自動リッスン）。`firmware/CMakeLists.txt` に `CONFIG_STACKCHAN_BACKEND_WAKE` define + PROJECT_VER 1.6.0。`idf.py build flash` 成功・実機で「ウェイクワードなしで auto 接続→listen」「非ウェイク発話は無視」を確認。ホストテスト緑。
- バックエンド: `STACKCHAN_WAKE_WORD_GATE_ENABLED=true` で有効化（ADR-0014）。端末のウェイクワードはダッシュボード/設定で任意の日本語に変更可（既定例: ベルちゃん/ベル）。
- 電力は増える（常時マイク+間欠送信）。バッテリ運用時は要再検討。
