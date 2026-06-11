"""Speech recognition value objects (design-spec §4.4 / §11.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechRecognitionResult:
    """Outcome of a speech-to-text recognition."""

    text: str
    language: str
    confidence: float
