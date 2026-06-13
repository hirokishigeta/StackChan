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
    """A single registered wake word (design-spec §8.1).

    ``threshold`` is the detection sensitivity in the closed range [0, 1]
    (higher = stricter / fewer false positives). ``phrase`` must be a
    non-empty, non-whitespace string.
    """

    id: str
    phrase: str
    model_name: str = "default"
    threshold: float = 0.7
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.phrase or not self.phrase.strip():
            raise ValueError("wake word phrase must not be empty")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"wake word threshold must be within [0, 1], got {self.threshold!r}")
