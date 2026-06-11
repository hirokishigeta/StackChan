"""Wake word detector port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.wakeword.entities import WakeWordConfig
from app.domain.wakeword.value_objects import WakeWordEntry


class WakeWordDetector(ABC):
    """Abstraction over backend-side wake word detection (design-spec §8.3)."""

    @abstractmethod
    async def detect(
        self,
        *,
        audio: bytes,
        config: WakeWordConfig,
    ) -> WakeWordEntry | None:
        """Return the matched wake word, or ``None`` if no match."""
        raise NotImplementedError
