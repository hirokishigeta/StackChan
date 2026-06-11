"""Settings repository port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.bot.entities import Bot
from app.domain.settings.entities import BotSettings


class SettingsRepository(ABC):
    """Persistence abstraction for Bots and their settings."""

    @abstractmethod
    def save_bot(self, bot: Bot) -> None:
        """Persist (insert or update) a Bot."""
        raise NotImplementedError

    @abstractmethod
    def get_bot(self, device_id: str) -> Bot | None:
        """Return a Bot by device id, or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def list_bots(self) -> list[Bot]:
        """Return all registered Bots."""
        raise NotImplementedError

    @abstractmethod
    def save_settings(self, settings: BotSettings) -> None:
        """Persist the settings aggregate for a device."""
        raise NotImplementedError

    @abstractmethod
    def get_settings(self, device_id: str) -> BotSettings | None:
        """Return the settings for a device, or ``None`` if unknown."""
        raise NotImplementedError
