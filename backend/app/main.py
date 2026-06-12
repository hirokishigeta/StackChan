"""FastAPI entry point.

Wires the API routers and the dashboard. Concrete dependencies are resolved
in ``app.di_container`` only (design-spec §4.2).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.interfaces.api import (
    agent_routes,
    bot_audio_ws,
    bot_routes,
    settings_routes,
    speech_routes,
    vision_routes,
)
from app.interfaces.dashboard import routes as dashboard_routes


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

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
