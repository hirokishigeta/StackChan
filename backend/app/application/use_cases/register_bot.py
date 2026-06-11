"""Use case: register a Bot device."""

from __future__ import annotations

from app.application.ports.settings_repository import SettingsRepository
from app.domain.bot.entities import Bot
from app.domain.bot.services import register_bot
from app.domain.settings.entities import BotSettings


class RegisterBotUseCase:
    """Register (or re-register) a Bot and ensure default settings exist."""

    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository

    def execute(self, *, device_id: str, firmware_version: str) -> tuple[Bot, BotSettings]:
        """Persist the Bot and return it with its settings."""
        bot = register_bot(device_id=device_id, firmware_version=firmware_version)
        self._repository.save_bot(bot)

        settings = self._repository.get_settings(device_id)
        if settings is None:
            settings = BotSettings.default(device_id)
            self._repository.save_settings(settings)
        return bot, settings
