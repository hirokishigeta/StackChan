"""Voice runtime-config provider port (ABC, ADR-0009).

The TTS synthesizer (infrastructure) depends on this abstraction rather than
on a concrete use case, so it can read the *effective* voice settings per-call
without importing the application layer. ``ManageServerSettingsUseCase``
provides the concrete implementation, wired in di_container.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.settings.value_objects import ServerVoiceSettings


class VoiceConfigProvider(ABC):
    """Supplies the currently-effective server voice settings."""

    @abstractmethod
    def current_voice(self) -> ServerVoiceSettings:
        """Return the effective voice settings (override over env defaults)."""
        raise NotImplementedError

    @abstractmethod
    def selected_reference_wav(self) -> str | None:
        """Resolve the selected voice sample's wav path, or ``None`` (ADR-0012).

        ``None`` means no sample is selected (or it no longer resolves); the
        synthesizer then falls back to ``irodori_reference_wav_path`` else
        no_ref.
        """
        raise NotImplementedError
