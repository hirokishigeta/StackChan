"""Use case: read / update the server-global voice (TTS) settings (ADR-0009).

The effective voice settings are the persisted dashboard override layered onto
the ``AppSettings`` / env defaults: each field falls back to its default when
the override has never been set. This is the single place that computes the
effective value, so both the API and the TTS synthesizer see the same result.
"""

from __future__ import annotations

from app.application.ports.server_settings_repository import ServerSettingsRepository
from app.application.ports.voice_config_provider import VoiceConfigProvider
from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.config.settings import AppSettings
from app.domain.settings.value_objects import ServerHermesSettings, ServerVoiceSettings


class UnknownVoiceSampleError(ValueError):
    """Raised when a selected ``voice_sample_id`` is not in the catalogue."""


class ManageServerSettingsUseCase(VoiceConfigProvider):
    """Compute, read and update the effective server voice settings."""

    def __init__(
        self,
        repository: ServerSettingsRepository,
        settings: AppSettings,
        voice_samples: VoiceSampleRepository,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._voice_samples = voice_samples

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
        """Persist and return the updated voice override.

        A non-null ``voice_sample_id`` that is not in the catalogue raises
        :class:`UnknownVoiceSampleError` (the API maps it to HTTP 422).
        """
        if voice.voice_sample_id is not None:
            if self._voice_samples.resolve_wav_path(voice.voice_sample_id) is None:
                raise UnknownVoiceSampleError(voice.voice_sample_id)
        self._repository.save_voice_override(voice)
        return voice

    def current_hermes(self) -> ServerHermesSettings:
        """Return effective Hermes settings: override if present else env defaults.

        The API key is never part of this value: it stays env-only.
        """
        override = self._repository.get_hermes_override()
        if override is not None:
            return override
        return ServerHermesSettings(
            base_url=self._settings.hermes_base_url,
            model=self._settings.hermes_model,
            dashboard_url=self._settings.hermes_dashboard_url,
        )

    def update_hermes(self, hermes: ServerHermesSettings) -> ServerHermesSettings:
        """Persist and return the updated Hermes connection override."""
        self._repository.save_hermes_override(hermes)
        return hermes

    def selected_reference_wav(self) -> str | None:
        """Resolve the selected sample's wav path, or ``None`` if none selected.

        Used by the synthesizer to clone a fixed timbre. A selected id that no
        longer resolves (sample removed) yields ``None`` so synthesis still
        proceeds with the next fallback rather than failing.
        """
        sample_id = self.current_voice().voice_sample_id
        if sample_id is None:
            return None
        return self._voice_samples.resolve_wav_path(sample_id)
