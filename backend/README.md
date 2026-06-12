# StackChan Backend

PC-side AI backend for the StackChan CoreS3 AI Bot. Python 3.11+ / FastAPI,
built with Clean Architecture + DDD. See `docs/design-spec.md` (§4, §10, §11)
and `docs/adr/0002`, `docs/adr/0004` for the design.

> This is the **Phase 2** scaffold: a minimal structure + a working `make check`
> base. AI logic (agent / speech / vision / wake word) is **dummy** and is
> filled in by later phases (see TODOs in `app/infrastructure/`).

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

## Commands

```bash
make setup   # uv sync --extra dev (create venv + install deps)
make fmt     # ruff format + ruff check --fix
make lint    # ruff check + mypy app
make test    # pytest
make check   # fmt -> lint -> test (run before committing)
make run     # uvicorn app.main:app --reload
```

## Layout (Clean Architecture + DDD)

```
app/
  main.py                 # FastAPI entry point (app factory)
  config/settings.py      # env-driven settings (no hard-coded URLs/models)
  domain/                 # entities / value_objects / services (no external deps)
    bot/ agent/ speech/ vision/ wakeword/ settings/
  application/
    use_cases/            # register_bot, process_agent_request, ...
    ports/                # ABCs: agent_gateway, speech_recognizer, ...
  infrastructure/         # concrete port implementations (dummy + sqlite)
    agent/ speech/ vision/ wakeword/ persistence/ transport/
  interfaces/
    api/                  # bot/agent/speech/vision/settings routes (design-spec §11)
    dashboard/            # minimal HTML bot-list (design-spec §10)
  di_container/           # the only place concretes are wired (FastAPI Depends)
tests/
```

Dependency rule (one direction, outer -> inner):
`interfaces -> application -> domain`,
`infrastructure -> application/ports -> domain`. `config` is referenceable
from any layer. The domain depends on no external library.

## API (design-spec §11)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/bot/register` | register a Bot, returns settings (§11.1) |
| GET | `/api/bot/{device_id}/commands` | drain queued control commands (§11.5) |
| GET | `/api/bot/{device_id}/wakeword` | active wake words, multi-word (§11.6) |
| POST | `/api/speech/recognize` | dummy ASR (§11.2) |
| POST | `/api/agent/chat` | dummy agent (§11.3) |
| POST | `/api/vision/detect` | dummy detection (§11.4) |
| GET/PUT | `/api/settings/{device_id}` | full settings aggregate (§10) |
| GET | `/` , `/dashboard` | minimal dashboard (§10) |
| GET | `/health` | liveness |

Per ADR-0004, the firmware speaks the xiaozhi-compatible message schema; these
APIs are the **backend-internal canonical API**, and a future adapter bridges
the two.

## Persistence

SQLite via SQLModel/SQLAlchemy (`STACKCHAN_DATABASE_URL`, default
`sqlite:///./stackchan.db`). The settings aggregate is stored as JSON; the
`SettingsRepository` port keeps persistence out of the domain.

## Running with real models (ASR / audio)

Providers are dummy by default so `make check` runs with no native deps. To run
real recognition/audio, install the optional extras and point settings at model
files. Copy `.env.example` to `.env` and fill it in (`.env` is gitignored).

```bash
# 1) optional native extras (sherpa-onnx ASR + libopus binding)
uv sync --extra dev --extra sherpa --extra opus
#    macOS arm64: the PyPI sherpa-onnx wheel ships no onnxruntime; pyproject's
#    [tool.uv] find-links + the `sherpa-onnx-core` dep pull the bundled official
#    k2-fsa wheel automatically. libopus: `brew install opus`.

# 2) Japanese ASR model (ReazonSpeech zipformer transducer)
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2
tar xjf sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2

# 3) point .env at the 4 model files (see .env.example) and set STACKCHAN_OTA_WS_HOST
#    to the backend's LAN IP, then run including the extras:
uv run --extra sherpa --extra opus uvicorn app.main:app --host 0.0.0.0
```

> The Python version is pinned to 3.13 (`.python-version`): the ML wheels
> (sherpa-onnx / torch) do not yet ship for 3.14. Tests are hermetic w.r.t. a
> local `.env` (conftest disables env-file loading).

Downlink TTS (Irodori-TTS, ADR-0006) needs the `[tts]` extra + a GPU and its
adapter is still a TODO (#7-b); keep `STACKCHAN_DEFAULT_TTS_PROVIDER=dummy`
(text-only downlink) until that is wired on a GPU host.
```
