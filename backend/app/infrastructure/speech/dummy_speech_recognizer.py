"""Dummy SpeechRecognizer returning fixed text.

TODO(issue#7): replace with faster-whisper / sherpa-onnx based recognizer
and add WebSocket streaming (design-spec §7.6 / §11.8).
"""

from __future__ import annotations

from app.application.ports.speech_recognizer import SpeechRecognizer
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import SpeechRecognitionResult


class DummySpeechRecognizer(SpeechRecognizer):
    """Returns a fixed transcription regardless of audio."""

    async def recognize(
        self,
        *,
        audio: bytes,
        config: SpeechRecognitionConfig,
    ) -> SpeechRecognitionResult:
        return SpeechRecognitionResult(text="こんにちは", language=config.language, confidence=0.92)
