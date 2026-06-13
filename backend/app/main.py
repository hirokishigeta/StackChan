"""FastAPI entry point.

Wires the API routers and the dashboard. Concrete dependencies are resolved
in ``app.di_container`` only (design-spec §4.2).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.interfaces.api import (
    agent_routes,
    bot_audio_ws,
    bot_routes,
    ota_routes,
    settings_routes,
    speech_routes,
    vision_routes,
)
from app.interfaces.dashboard import routes as dashboard_routes

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Preload the TTS runtime in the background so the first turn is fast.

    Runs off the event loop (torch model load is blocking) and never blocks
    startup or fails it: warm-up errors are logged and deferred to the first
    synthesize. No-op for lightweight engines (their ``warm_up`` is a no-op).
    """
    settings = get_settings()
    if settings.tts_warm_up_on_startup:
        from app.di_container.container import get_container

        async def _warm() -> None:
            try:
                synth = get_container().speech_synthesizer
                logger.info("TTS warm-up: preloading %s", settings.default_tts_provider)
                await asyncio.to_thread(synth.warm_up)
                logger.info("TTS warm-up: done")
            except Exception:  # noqa: BLE001 - warm-up must never break startup
                logger.exception("TTS warm-up failed (deferred to first turn)")

        asyncio.create_task(_warm())
    yield


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=_lifespan)

    # LAN-only CORS (design-spec §13 security). Origins are configurable.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(bot_routes.router)
    app.include_router(bot_audio_ws.router)
    app.include_router(ota_routes.router)
    app.include_router(agent_routes.router)
    app.include_router(speech_routes.router)
    app.include_router(vision_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(dashboard_routes.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
