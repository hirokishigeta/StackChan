"""Use case: recognize speech audio into text."""

from __future__ import annotations

from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import SpeechRecognitionResult


class ProcessVoiceInputUseCase:
    """Run speech recognition using the device's stored speech config."""

    def __init__(self, recognizer: SpeechRecognizer, repository: SettingsRepository) -> None:
        self._recognizer = recognizer
        self._repository = repository

    async def execute(
        self,
        *,
        audio: bytes,
        device_id: str | None = None,
    ) -> SpeechRecognitionResult:
        """Transcribe audio. Falls back to default config when device unknown."""
        config = SpeechRecognitionConfig()
        if device_id is not None:
            settings = self._repository.get_settings(device_id)
            if settings is not None:
                config = settings.speech
        return await self._recognizer.recognize(audio=audio, config=config)
