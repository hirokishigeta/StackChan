# ADR-0016: デバイスごとの会話終了ワード（ダッシュボード設定）

- Status: Accepted
- Date: 2026-06-14
- 関連: ADR-0011（複数ウェイクワード）/ ADR-0014（バックエンド側ウェイクワード・ゲート）/ docs/design-spec.md §8

## コンテキスト

ADR-0014 のウェイクワード・ゲートでは、engage 済みの会話を「終了ワード」で終わらせる。
従来この終了ワードはグローバルな環境設定 `AppSettings.conversation_end_words`（全デバイス共通）
だけで、デバイスごとに変更できなかった。ウェイクワードは ADR-0011 で既にデバイスごとに
（フレーズ一覧として）ダッシュボードから編集できるため、終了ワードも同じ方式で
デバイスごとに設定できるべき、という要望が出た。

## 決定

終了ワードをウェイクワードと同じパターンでデバイスごとに設定可能にする。

- ドメインに `EndWordEntry`（`id` / `phrase` / `enabled`、空フレーズは `ValueError`）と
  `EndWordConfig`（`end_words` 一覧）を追加し、`BotSettings.end_word` として公開する。
  これは `WakeWordEntry` / `WakeWordConfig` のパターンの踏襲。
- 既定の日本語終了ワード一覧は単一の定数 `DEFAULT_END_WORD_PHRASES` に置き、
  デバイス既定（`DEFAULT_END_WORDS`）とグローバルフォールバック
  （`AppSettings.conversation_end_words`）の両方がこれを参照する（リテラル重複の排除）。
- WS ゲートは listen 開始時にデバイスの有効な終了ワードを `_resolve_end_words` で解決し、
  `_Session.end_words` にキャッシュする（`wake_words` と同じ流儀）。会話終了判定では
  そのデバイス終了ワードを使い、**デバイスに未設定（空）の場合のみ**グローバルの
  `AppSettings.conversation_end_words` にフォールバックする（既存デプロイは無編集なら従来挙動）。
- マッチは既存のドメイン純粋関数 `matches_wake_word(text, words)` をそのまま使う。
- 永続化では `end_word` キーが無い（旧データ）場合はデバイス既定一覧にフォールバックし、
  キーがある場合（空一覧含む）はそれを正とする。設定 PUT は空フレーズを 422 で拒否する。
- ダッシュボードの「ウェイクワード」タブに「会話終了ワード」セクションを追加し、
  既存のウェイクワード行と同じ vanilla-JS ヘルパー・スタイルで動的に追加・削除・保存する。

## 検討した選択肢

- 選択肢 A: `ConversationTurnConfig` に `end_words: tuple[str, ...]` を追加する。
  - メリット: 値オブジェクトが増えない。
  - デメリット: ウェイクワードの「有効/無効フラグ付きエントリ一覧」と非対称になり、
    ダッシュボード UI もウェイクワードと別仕立てになる。
- 選択肢 B（採用）: ウェイクワードと同型の `EndWordEntry` / `EndWordConfig` を追加。
  - メリット: ウェイクワード機能と UI・シリアライズ・解決ロジックを完全に対称化でき、
    `matches_wake_word` をそのまま再利用できる。
  - デメリット: 値オブジェクトが 1 つ増える。

## 理由

ウェイクワードと終了ワードは「デバイスごとのフレーズ一覧で会話の開始/終了を制御する」
対称な関心事であり、同じパターンに揃えるのが UI・永続化・テストの一貫性で最も素直。
グローバル設定へのフォールバックにより、既存デプロイは編集するまで挙動が変わらない。

## 影響

- ドメイン `wakeword/`（`EndWordEntry` / `EndWordConfig` / `DEFAULT_END_WORD_PHRASES` /
  `DEFAULT_END_WORDS`）、`settings/entities.py`（`BotSettings.end_word`）、
  `config/settings.py`（グローバル既定を共有定数から導出）、`serialization.py`、
  `settings_routes`（既存の値オブジェクト検証で 422）、`bot_audio_ws`（`_resolve_end_words` /
  `_Session.end_words`）、ダッシュボード HTML を変更。
- ビジネスロジックはドメインに閉じ込め、プレゼンテーション層は解決結果を使うだけ（CLAUDE.md）。
- フォローアップ: ファームに終了ワードのデバイス側 UI が必要になれば別途検討。
