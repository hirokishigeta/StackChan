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
