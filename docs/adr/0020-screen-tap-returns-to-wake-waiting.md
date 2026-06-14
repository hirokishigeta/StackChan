# ADR-0020: 画面タップで会話終了 → ウェイク待ちに戻す

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0014 (backend wake gate) / ADR-0015 (firmware backend-wake) / docs/design-spec.md §7

## コンテキスト

backend-wake / always-listen 構成（ADR-0014/0015）では、会話の開始・継続・終了をバックエンドのウェイクゲートが管理する。会話を能動的に終わらせる手段は「終了ワードの発話」または「idle タイムアウト」しかなく、ユーザーが即座に会話を打ち切ってウェイク待ちへ戻す物理操作がなかった。

CoreS3 のアバターパネルには既に `onClick`（タップ）ハンドラがあるが、既存実装は `Application::ToggleChatState()` を呼ぶ。これは LISTENING 状態では `CloseAudioChannel()` を呼んでしまい、always-listen のストリームを切断する（＝以後ウェイクに反応しなくなる）ため backend-wake 構成と相性が悪い。

## 決定

backend-wake ビルド（`CONFIG_STACKCHAN_BACKEND_WAKE`）では、画面タップで **会話を終了してウェイク待ちに戻す**。音声チャンネルは閉じない。

- Firmware: `Application::ReturnToWakeWaiting()` を新設。発話中なら `AbortSpeaking` で再生停止＋abort 送信、それ以外は `SendAbortSpeaking` で abort 信号のみ送信。`conversation_engaged_` をローカルで false にし、インジケータを待機色へ即時更新する。`hal_bridge::request_wake_waiting()` 経由で `onClick` から呼ぶ。
- Backend: `{"type":"abort"}` 受信時（`_handle_abort`）に、従来の TTS 停止に加えて `session.engaged=False` とし `{"type":"wake","state":"waiting"}` を返す。次ターンは再度ウェイク語が必要になる。
- backend-wake が無効な従来ビルドでは `toggle_xiaozhi_chat_state()` のまま（挙動不変）。

## 検討した選択肢

- 選択肢 A（採用）: タップ→abort 送信、backend がゲートを disengage。always-listen を維持したまま会話だけ終了。
- 選択肢 B: 専用メッセージ `{"type":"wake","state":"abort"}` を新設。意味は明確だが、backend-wake ではデバイス側ウェイクが無効で abort の発生源がタップのみのため、既存 abort を流用すれば配線を増やさず済む。
- 選択肢 C: 既存 `ToggleChatState` のまま。LISTENING で音声チャンネルを閉じ always-listen が壊れるため不可。

## 理由

既存の abort パスを再利用することで、firmware・backend ともに最小変更で済む。backend-wake ではデバイス側ウェイクネットが無効なので abort の唯一の発生源はユーザータップであり、abort=会話終了という意味づけが破綻しない。音声チャンネルを閉じないためウェイク待ちが維持される。

## 影響

- backend-wake で abort は「会話終了→ウェイク待ち」を意味するようになる（barge-in 専用ではなくなる）。device 側ウェイクを使う構成では `_send_engagement_state` がゲート無効時に早期 return するため影響なし。
- firmware は ESP-IDF 未導入環境のためビルド未確認・clang-format 未適用。実機ビルド/フラッシュ時に確認すること。
- フォローアップ: タップ以外（頭なでジェスチャ等）からの会話終了が必要なら同じ `ReturnToWakeWaiting()` を流用できる。
