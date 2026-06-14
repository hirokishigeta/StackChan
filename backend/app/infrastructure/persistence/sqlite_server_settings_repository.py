"""SQLite-backed ServerSettingsRepository (ADR-0009).

Stores the single server-global voice override as one JSON row (fixed primary
key). Reuses the SQLModel engine pattern of ``SqliteSettingsRepository``; the
table is independent so per-device settings and server settings never collide.
"""

from __future__ import annotations

import json

from sqlmodel import Field, Session, SQLModel, create_engine

from app.application.ports.server_settings_repository import ServerSettingsRepository
from app.domain.settings.value_objects import ServerHermesSettings, ServerVoiceSettings

# Fixed primary key: there is exactly one server-global voice override row.
_VOICE_ROW_ID = "voice"
# Fixed primary key: there is exactly one server-global Hermes override row.
_HERMES_ROW_ID = "hermes"


class ServerVoiceRow(SQLModel, table=True):
    """Persistence row holding the server voice override as JSON."""

    __tablename__ = "server_voice_settings"

    id: str = Field(default=_VOICE_ROW_ID, primary_key=True)
    payload: str  # JSON-encoded ServerVoiceSettings


class ServerHermesRow(SQLModel, table=True):
    """Persistence row holding the server Hermes connection override as JSON."""

    __tablename__ = "server_hermes_settings"

    id: str = Field(default=_HERMES_ROW_ID, primary_key=True)
    payload: str  # JSON-encoded ServerHermesSettings


class SqliteServerSettingsRepository(ServerSettingsRepository):
    """ServerSettingsRepository backed by SQLite."""

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self._engine)

    def get_voice_override(self) -> ServerVoiceSettings | None:
        with Session(self._engine) as session:
            row = session.get(ServerVoiceRow, _VOICE_ROW_ID)
            if row is None:
                return None
            data = json.loads(row.payload)
            return ServerVoiceSettings(
                tts_provider=data["tts_provider"],
                irodori_caption=data["irodori_caption"],
                irodori_base_style=data["irodori_base_style"],
                # Back-compat: rows written before ADR-0012 have no key -> None.
                voice_sample_id=data.get("voice_sample_id"),
            )

    def save_voice_override(self, voice: ServerVoiceSettings) -> None:
        payload = json.dumps(
            {
                "tts_provider": voice.tts_provider,
                "irodori_caption": voice.irodori_caption,
                "irodori_base_style": voice.irodori_base_style,
                "voice_sample_id": voice.voice_sample_id,
            },
            ensure_ascii=False,
        )
        with Session(self._engine) as session:
            row = session.get(ServerVoiceRow, _VOICE_ROW_ID)
            if row is None:
                row = ServerVoiceRow(id=_VOICE_ROW_ID, payload=payload)
            else:
                row.payload = payload
            session.add(row)
            session.commit()

    def get_hermes_override(self) -> ServerHermesSettings | None:
        with Session(self._engine) as session:
            row = session.get(ServerHermesRow, _HERMES_ROW_ID)
            if row is None:
                return None
            data = json.loads(row.payload)
            return ServerHermesSettings(
                # Back-compat: tolerate rows missing any key.
                base_url=data.get("base_url", ""),
                model=data.get("model", ""),
                dashboard_url=data.get("dashboard_url", ""),
            )

    def save_hermes_override(self, hermes: ServerHermesSettings) -> None:
        payload = json.dumps(
            {
                "base_url": hermes.base_url,
                "model": hermes.model,
                "dashboard_url": hermes.dashboard_url,
            },
            ensure_ascii=False,
        )
        with Session(self._engine) as session:
            row = session.get(ServerHermesRow, _HERMES_ROW_ID)
            if row is None:
                row = ServerHermesRow(id=_HERMES_ROW_ID, payload=payload)
            else:
                row.payload = payload
            session.add(row)
            session.commit()
