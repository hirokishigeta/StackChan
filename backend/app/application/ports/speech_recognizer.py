"""Speech recognizer port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import SpeechRecognitionResult


class SpeechRecognizer(ABC):
    """Abstraction over a speech-to-text engine."""

    @abstractmethod
    async def recognize(
        self,
        *,
        audio: bytes,
        config: SpeechRecognitionConfig,
    ) -> SpeechRecognitionResult:
        """Transcribe audio bytes into text."""
        raise NotImplementedError
