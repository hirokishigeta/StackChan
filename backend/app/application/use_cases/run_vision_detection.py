"""Use case: run vision detection on a frame."""

from __future__ import annotations

from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.vision_recognizer import VisionRecognizer
from app.domain.vision.entities import VisionRecognitionConfig
from app.domain.vision.value_objects import VisionDetectionResult


class RunVisionDetectionUseCase:
    """Run vision detection using the device's stored vision config."""

    def __init__(self, recognizer: VisionRecognizer, repository: SettingsRepository) -> None:
        self._recognizer = recognizer
        self._repository = repository

    async def execute(
        self,
        *,
        image: bytes,
        device_id: str | None = None,
    ) -> VisionDetectionResult:
        """Detect objects in an image frame."""
        config = VisionRecognitionConfig()
        if device_id is not None:
            settings = self._repository.get_settings(device_id)
            if settings is not None:
                config = settings.vision
        return await self._recognizer.detect(image=image, config=config)
