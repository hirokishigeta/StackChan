"""Wake word entities (design-spec §4.4 / §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .value_objects import DetectionMethod, WakeWordEntry


@dataclass(frozen=True)
class WakeWordConfig:
    """Wake word configuration. Supports multiple wake words (design-spec §8.1)."""

    enabled: bool = True
    detection_method: DetectionMethod = DetectionMethod.LOCAL
    # Max wake words simultaneously active on the device side (design-spec §8.1).
    max_local_active: int = 3
    wake_words: tuple[WakeWordEntry, ...] = field(default_factory=tuple)
