"""Wake word domain services."""

from __future__ import annotations

from .entities import WakeWordConfig
from .value_objects import DetectionMethod, WakeWordEntry


def resolve_active_wake_words(config: WakeWordConfig) -> tuple[WakeWordEntry, ...]:
    """Return the wake words that should be active.

    For device-side (``local``) detection, the number of simultaneously
    active wake words is capped by ``max_local_active`` (design-spec §8.1);
    the overflow is intended to be delegated to backend-side detection or
    disabled. For backend-side detection there is no cap.
    """
    enabled = tuple(w for w in config.wake_words if w.enabled)
    if config.detection_method is DetectionMethod.LOCAL:
        return enabled[: config.max_local_active]
    return enabled
