"""SQLite-backed SettingsRepository (working implementation).

Uses SQLModel/SQLAlchemy for the engine and stores the settings aggregate as
a JSON column. Bots and settings are keyed by ``device_id``.
"""

from __future__ import annotations

import json

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.application.ports.settings_repository import SettingsRepository
from app.domain.bot.entities import Bot
from app.domain.bot.value_objects import BotCapabilities, ConnectionStatus
from app.domain.settings.entities import BotSettings

from .serialization import settings_from_dict, settings_to_dict


class BotRow(SQLModel, table=True):
    """Persistence row for a Bot."""

    __tablename__ = "bots"

    device_id: str = Field(primary_key=True)
    name: str
    firmware_version: str
    backend_url: str | None = None
    connection_status: ConnectionStatus = Field(
        sa_column=Column(SAEnum(ConnectionStatus), nullable=False)
    )
    current_expression: str = "neutral"
    last_seen_at: str | None = None


class SettingsRow(SQLModel, table=True):
    """Persistence row holding the settings aggregate as JSON."""

    __tablename__ = "bot_settings"

    device_id: str = Field(primary_key=True)
    payload: str  # JSON-encoded BotSettings


class SqliteSettingsRepository(SettingsRepository):
    """SettingsRepository backed by SQLite."""

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self._engine)

    # -- Bot ---------------------------------------------------------------

    def save_bot(self, bot: Bot) -> None:
        with Session(self._engine) as session:
            row = session.get(BotRow, bot.device_id)
            if row is None:
                row = BotRow(
                    device_id=bot.device_id,
                    name=bot.name,
                    firmware_version=bot.firmware_version,
                    backend_url=bot.backend_url,
                    connection_status=bot.connection_status,
                    current_expression=bot.current_expression,
                    last_seen_at=bot.last_seen_at,
                )
            else:
                row.name = bot.name
                row.firmware_version = bot.firmware_version
                row.backend_url = bot.backend_url
                row.connection_status = bot.connection_status
                row.current_expression = bot.current_expression
                row.last_seen_at = bot.last_seen_at
            session.add(row)
            session.commit()

    def get_bot(self, device_id: str) -> Bot | None:
        with Session(self._engine) as session:
            row = session.get(BotRow, device_id)
            return self._row_to_bot(row) if row is not None else None

    def list_bots(self) -> list[Bot]:
        with Session(self._engine) as session:
            rows = session.exec(select(BotRow)).all()
            return [self._row_to_bot(row) for row in rows]

    # -- Settings ----------------------------------------------------------

    def save_settings(self, settings: BotSettings) -> None:
        payload = json.dumps(settings_to_dict(settings), ensure_ascii=False)
        with Session(self._engine) as session:
            row = session.get(SettingsRow, settings.device_id)
            if row is None:
                row = SettingsRow(device_id=settings.device_id, payload=payload)
            else:
                row.payload = payload
            session.add(row)
            session.commit()

    def get_settings(self, device_id: str) -> BotSettings | None:
        with Session(self._engine) as session:
            row = session.get(SettingsRow, device_id)
            if row is None:
                return None
            data = json.loads(row.payload)
            return settings_from_dict(device_id, data)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _row_to_bot(row: BotRow) -> Bot:
        return Bot(
            device_id=row.device_id,
            name=row.name,
            firmware_version=row.firmware_version,
            capabilities=BotCapabilities(),
            backend_url=row.backend_url,
            connection_status=row.connection_status,
            current_expression=row.current_expression,
            last_seen_at=row.last_seen_at,
        )
