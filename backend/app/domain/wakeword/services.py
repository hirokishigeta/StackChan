"""Wake word domain services."""

from __future__ import annotations

from .entities import WakeWordConfig
from .value_objects import WakeWordEntry


def resolve_active_wake_words(config: WakeWordConfig) -> tuple[WakeWordEntry, ...]:
    """Return the wake words that should be active.

    All enabled wake words are active. The legacy device-side cap
    (``max_local_active``) was removed (ADR-0017): backend detection is gated by
    ``AppSettings.wake_word_gate_enabled`` and on-device wake uses a fixed
    compiled model, so neither path consumed a per-config cap.
    """
    return tuple(w for w in config.wake_words if w.enabled)
