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
```
