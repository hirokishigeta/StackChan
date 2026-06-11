"""Dummy WakeWordDetector.

TODO(issue#7): replace with a real backend-side wake word model and
honour per-entry thresholds / models (design-spec §8).
"""

from __future__ import annotations

from app.application.ports.wakeword_detector import WakeWordDetector
from app.domain.wakeword.entities import WakeWordConfig
from app.domain.wakeword.services import resolve_active_wake_words
from app.domain.wakeword.value_objects import WakeWordEntry


class DummyWakeWordDetector(WakeWordDetector):
    """Returns the first active wake word as a stand-in match."""

    async def detect(
        self,
        *,
        audio: bytes,
        config: WakeWordConfig,
    ) -> WakeWordEntry | None:
        active = resolve_active_wake_words(config)
        return active[0] if active else None
