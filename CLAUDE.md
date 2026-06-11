# CLAUDE.md

M5Stack CoreS3 上で動作する AI デスクトップロボット StackChan の OSS モノレポ。
本リポジトリでは、CoreS3 を「AI に身体を与える入出力端末」とし、AI 処理（LLM / Agent / 音声認識 / 画像認識 / Wake Word / 設定管理）を PC 上の Python バックエンドへ集約する改修を進める。

**設計の全体像は `docs/design-spec.md` を必ず先に読むこと。設計判断は `docs/adr/` に ADR として残すこと。**

## モノレポ構成

| ディレクトリ | 内容 | 技術スタック |
|---|---|---|
| `firmware/` | CoreS3 ファームウェア（改修の主対象） | C++ / ESP-IDF v5.5.4 / LVGL 9.4 / esp-sr / esp32-camera |
| `backend/` | PC 上の AI バックエンド（新設、改修の中核） | Python 3.11+ / FastAPI |
| `server/` | 既存の公式クラウドサーバー（アカウント・アプリストア・XiaoZhi 連携）。**今回の改修対象外。原則触らない** | Go 1.24+ / GoFrame v2 / MySQL |
| `app/` | モバイルアプリ | Flutter / Dart |
| `remote/` | ESP-NOW リモコンファームウェア | C++ / ESP-IDF |

注意: 新設する PC バックエンドは既存 `server/`（Go）とは目的が異なる（LAN ローカルの AI 処理 vs クラウドのアカウント基盤）。`backend/` として分離する（ADR-0002）。

## コマンド

**すべての実装タスクは、変更したコンポーネントの fmt → lint → build → test を完了させてから終わりにすること。1つでも失敗したまま「完了」としない。** これは例外なく徹底する。

### firmware/（ESP-IDF）

```bash
cd firmware
python3 ./fetch_repos.py    # 初回のみ: 依存リポジトリ取得
idf.py build                # ビルド（変更後は必ず通すこと）
idf.py flash                # 書き込み
clang-format -i <変更ファイル>   # フォーマット（.clang-format 準拠 / Google style）
cmake -S tests -B build-host-tests && ctest --test-dir build-host-tests --output-on-failure   # ホスト側テスト
```

- ESP-IDF 環境がないマシンでは `idf.py build` が実行できない。その場合は「ビルド未確認」と明示し、ホスト側テストと clang-format のみ実行する。断定的に「ビルドが通る」と報告しない。

### backend/（Python / FastAPI、新設）

```bash
cd backend
make setup   # 初回セットアップ（uv + 依存インストール）
make fmt     # ruff format + ruff check --fix（import 整列含む）
make lint    # ruff check + mypy
make test    # pytest
make check   # fmt + lint + test（コミット前に必ず実行）
```

- backend 新設時にこの Makefile を最初に整備すること。`make check` が通らないコードはコミットしない。

### server/（Go、原則変更しない）

やむを得ず触る場合のみ:

```bash
cd server
gofmt -w . && go vet ./...
go build ./...
go test ./...
```

### app/（Flutter）

```bash
cd app
flutter pub get
dart format .
flutter analyze
flutter test
flutter build apk --debug   # ビルド確認
```

## フォルダ構成

### backend/（クリーンアーキテクチャ + DDD）

```
backend/
  app/
    main.py                  # FastAPI エントリポイント

    domain/                  # ドメイン層。他のどの層にも依存しない
      bot/ agent/ speech/ vision/ wakeword/ settings/
        entities.py value_objects.py services.py

    application/             # ユースケース層
      use_cases/             # process_voice_input.py など
      ports/                 # 抽象インターフェース（ABC）
        agent_gateway.py speech_recognizer.py vision_recognizer.py
        wakeword_detector.py settings_repository.py bot_event_publisher.py

    infrastructure/          # ports の具象実装のみを置く
      agent/                 # hermes_agent_gateway.py / openclaw_gateway.py / openai_compatible_gateway.py
      speech/ vision/ wakeword/
      persistence/           # sqlite_settings_repository.py
      transport/             # websocket_bot_event_publisher.py

    interfaces/              # プレゼンテーション層
      api/                   # bot_routes.py / agent_routes.py / speech_routes.py ...
      dashboard/             # routes.py / schemas.py

    di_container/            # 唯一の具象依存解決ポイント

    config/                  # 設定・定数。どの層からも参照可
      settings.py
  tests/
```

### firmware/（責務分離の目標構成）

既存は `main/main.cpp`（約1,800行）+ `hal/`（HAL 層）+ `stackchan/`（アバター・モーション）+ `apps/` の構成。
改修では既存構成を活かしつつ、`docs/design-spec.md` §3.3 の方向（domain / application / infrastructure / presentation）へ段階的に分離する。

- 既存の `hal/` は infrastructure/hardware に相当する。**一括リネームや大規模移動はしない**。新規コードから新構造に置き、既存コードは触るタイミングで段階的に移す
- `main.cpp` に処理を追加しない。新機能は必ず分離したモジュールに置く

## アーキテクチャ制約

### backend/ レイヤー依存ルール

依存は外→内の一方向のみ。内側のレイヤーは外側を参照しない。

```
interfaces → application → domain
infrastructure → application/ports → domain
                  ↑
                config（どの層からも参照可）
```

- **domain/**: FastAPI / DB / OpenAI SDK / OpenCV / どの外部ライブラリにも依存しない。純粋なエンティティとビジネスロジック
- **application/ports/**: 外部依存（Agent / ASR / Vision / WakeWord / 永続化 / イベント配信）は必ず ABC で抽象を定義する
- **infrastructure/**: ports の ABC を実装する具象クラスのみ。`interfaces/` に依存しない
- **interfaces/**: application のユースケースを呼ぶだけ。ビジネスロジックを書かない
- **di_container/**: 具象クラスの結合はここだけで行う。サービス層は常にインターフェースに依存する

### リポジトリ / Gateway パターン

外部 API・モデル・データソースは必ず「ports に ABC、infrastructure に具象」の組で実装する。
Provider の追加は具象クラスの追加 + DI 登録で行う。**if 文による Provider 分岐を増やさない。**

```
application/ports/agent_gateway.py        # ABC
infrastructure/agent/openai_compatible_gateway.py   # 具象（最初に実装）
infrastructure/agent/hermes_agent_gateway.py        # 具象（Adapter として追加）
```

### firmware/ の制約

- ハードウェア依存（マイク / スピーカー / カメラ / ディスプレイ / サーボ）は HAL（infrastructure/hardware）に閉じ込める
- API 通信・設定保存・Bot 状態管理・画面描画はそれぞれ分離する
- メモリ制約を常に意識する（PSRAM 8MB / Flash 16MB）。フレームバッファ・音声バッファを安易に複製しない
- 重い AI 推論を firmware 側に持ち込まない（design-spec §2.1 の役割分担に従う）
- 既存機能（画面設定・表情・モーション・既存アプリ）を壊さない。動作確認できないハードウェア処理は断定的に実装せず TODO を明示する

### server/（Go）・app/（Flutter）

既存構成（GoFrame の api / internal / controller / service / dao、Flutter の model / network / view）に従う。今回の改修では原則変更しない。変更する場合は ADR を残す。

## コーディング規約

### 共通

- **コミットメッセージ**: Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `test:`）。既存リポジトリに合わせて英語
- **PR**: 小さい単位で出す。1 PR = 1 関心事。変更前後でビルド・チェックが通ることを PR 内に明記する
- **ハードコード禁止**: API URL・モデル名・閾値などは設定（config / 環境変数 / 設定ファイル）に置く
- 仕様が不明な箇所は推測で実装せず、`TODO(issue#)` として明示する

### Python（backend/）

- **フォーマッタ / リンタ**: ruff（format + check）、型チェックは mypy（strict 寄り）
- **ドメインモデル**: `@dataclass(frozen=True)` または Pydantic の `model_config = ConfigDict(frozen=True)` で不変にする
- **インターフェース**: ABC + `@abstractmethod`
- **DI**: di_container に集約（dependency-injector または FastAPI Depends ベースで統一）
- **テスト**: pytest。外部 API・モデル推論は必ず mock する。実機（CoreS3）依存のテストを CI 必須にしない

### C++（firmware/ / remote/）

- **フォーマッタ**: clang-format（リポジトリの `.clang-format`、Google style ベース）。変更したファイルは必ずかける
- 動的確保は起動時に寄せ、ループ内での頻繁な new / malloc を避ける
- FreeRTOS タスク間の共有状態はキューまたはミューテックスで保護する
- ESP-IDF コンポーネントの追加は `idf_component.yml` で管理する

### Go（server/）/ Dart（app/）

- Go: gofmt + go vet 必須。golangci-lint は未導入（導入する場合は ADR を残す）
- Dart: `dart format` + `flutter analyze`（analysis_options.yaml 準拠）

## ADR（Architecture Decision Record）

**設計上の意思決定はすべて `docs/adr/` に ADR として残す。** 履歴を消さない。

- ファイル名: `NNNN-<kebab-case-title>.md`（連番4桁）
- テンプレート: `docs/adr/template.md`
- ステータス: `Proposed` → `Accepted` / `Rejected` / `Superseded by ADR-NNNN`
- 一度 Accepted にした ADR は**編集で上書きしない**。決定を変える場合は新しい ADR を書き、旧 ADR を Superseded にする
- ADR を書く対象の例: 技術選定、レイヤー構成の変更、API 設計方針、処理場所の決定（CoreS3 側 / PC 側）、既存コンポーネント（server/ 等）への変更、規約の追加・変更
- 設計ドキュメント（`docs/design-spec.md` 等）を大きく変更するときも、変更理由を ADR に残す

## 進捗管理（GitHub Projects / カンバン）

- タスクは GitHub Issue として切り、リポジトリの Project（カンバン）で管理する: `Todo` → `In Progress` → `In Review` → `Done`
- Issue の粒度は「1 Issue = 1 PR で完結する単位」。design-spec の Phase（0〜8）をマイルストーン or ラベルで対応付ける
- 実装着手時に Issue を In Progress へ移し、PR に `Closes #N` を付ける
- 並行できる実装タスクは、サブエージェント（Agent ツール、必要に応じて Opus 指定）に Issue 単位で委譲してよい。その場合も**各エージェントの成果物に対して fmt / lint / build / test を通すこと**を完了条件にする
- `gh` CLI で Issue / Project を操作する

## ドキュメント

- `docs/design-spec.md` — 全体設計・仕様（改修の正）
- `docs/adr/` — 意思決定の履歴
- `docs/repository-analysis.md` — Phase 0 成果物（既存リポジトリ調査）
- `docs/architecture.md` — Phase 1 成果物（firmware 責務分離設計）
- `docs/backend-api.md` — Phase 2 成果物（backend API 仕様）

実装とドキュメントが食い違ったら、ドキュメントを直す PR を必ず添える。
