"""Use cases: read / update Bot settings and list Bots."""

from __future__ import annotations

from app.application.ports.settings_repository import SettingsRepository
from app.domain.bot.entities import Bot
from app.domain.settings.entities import BotSettings


class ManageSettingsUseCase:
    """Read and write the per-device settings aggregate."""

    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository

    def get_settings(self, device_id: str) -> BotSettings | None:
        """Return settings for a device, or ``None`` if unknown."""
        return self._repository.get_settings(device_id)

    def update_settings(self, settings: BotSettings) -> BotSettings:
        """Persist and return the updated settings aggregate."""
        self._repository.save_settings(settings)
        return settings

    def list_bots(self) -> list[Bot]:
        """Return all registered Bots (for the dashboard)."""
        return self._repository.list_bots()

    def get_bot(self, device_id: str) -> Bot | None:
        """Return a Bot by device id."""
        return self._repository.get_bot(device_id)
