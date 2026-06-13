"""Wake word entities (design-spec §4.4 / §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .value_objects import DetectionMethod, WakeWordEntry

# Default wake words for a freshly registered device (design-spec §8.1).
# Detection runs on-device (esp-sr / WakeNet, see ADR-0011); the backend only
# stores and serves this list. These are sensible starter phrases the user can
# edit / extend from the dashboard, not a hard-coded behavioural constant.
DEFAULT_WAKE_WORDS: tuple[WakeWordEntry, ...] = (
    WakeWordEntry(id="ww-default-1", phrase="スタックチャン"),
    WakeWordEntry(id="ww-default-2", phrase="ねえスタックチャン"),
)


@dataclass(frozen=True)
class WakeWordConfig:
    """Wake word configuration. Supports multiple wake words (design-spec §8.1)."""

    enabled: bool = True
    detection_method: DetectionMethod = DetectionMethod.LOCAL
    # Max wake words simultaneously active on the device side (design-spec §8.1).
    max_local_active: int = 3
    wake_words: tuple[WakeWordEntry, ...] = field(default_factory=lambda: DEFAULT_WAKE_WORDS)
