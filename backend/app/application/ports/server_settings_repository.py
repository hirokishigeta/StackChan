"""Server-settings repository port (ABC, ADR-0009).

Persists the runtime-mutable, server-global voice (TTS) override. Only the
fields the dashboard may change are stored; absent fields fall back to the
``AppSettings`` / env defaults at read time (handled in the use case).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.settings.value_objects import ServerVoiceSettings


class ServerSettingsRepository(ABC):
    """Persistence abstraction for the server-global voice override."""

    @abstractmethod
    def get_voice_override(self) -> ServerVoiceSettings | None:
        """Return the persisted voice override, or ``None`` if never set."""
        raise NotImplementedError

    @abstractmethod
    def save_voice_override(self, voice: ServerVoiceSettings) -> None:
        """Persist (insert or replace) the voice override."""
        raise NotImplementedError
