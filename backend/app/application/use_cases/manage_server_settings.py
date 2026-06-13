"""Use case: read / update the server-global voice (TTS) settings (ADR-0009).

The effective voice settings are the persisted dashboard override layered onto
the ``AppSettings`` / env defaults: each field falls back to its default when
the override has never been set. This is the single place that computes the
effective value, so both the API and the TTS synthesizer see the same result.
"""

from __future__ import annotations

from app.application.ports.server_settings_repository import ServerSettingsRepository
from app.application.ports.voice_config_provider import VoiceConfigProvider
from app.config.settings import AppSettings
from app.domain.settings.value_objects import ServerVoiceSettings


class ManageServerSettingsUseCase(VoiceConfigProvider):
    """Compute, read and update the effective server voice settings."""

    def __init__(self, repository: ServerSettingsRepository, settings: AppSettings) -> None:
        self._repository = repository
        self._settings = settings

    def _defaults(self) -> ServerVoiceSettings:
        return ServerVoiceSettings(
            tts_provider=self._settings.default_tts_provider,
            irodori_caption=self._settings.irodori_caption,
            irodori_base_style=self._settings.irodori_base_style,
        )

    def current_voice(self) -> ServerVoiceSettings:
        """Return effective voice settings: override if present else env defaults."""
        override = self._repository.get_voice_override()
        return override if override is not None else self._defaults()

    def update_voice(self, voice: ServerVoiceSettings) -> ServerVoiceSettings:
        """Persist and return the updated voice override."""
        self._repository.save_voice_override(voice)
        return voice
