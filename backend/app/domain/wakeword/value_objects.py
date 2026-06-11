"""Wake word value objects (design-spec §4.4 / §8 / §11.6)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DetectionMethod(StrEnum):
    """Where wake-word detection runs (design-spec §8.3)."""

    LOCAL = "local"  # CoreS3-side detection
    BACKEND = "backend"  # PC-side detection


@dataclass(frozen=True)
class WakeWordEntry:
    """A single registered wake word (design-spec §8.1)."""

    id: str
    phrase: str
    model_name: str = "default"
    threshold: float = 0.7
    enabled: bool = True
