"""Vision recognizer port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.vision.entities import VisionRecognitionConfig
from app.domain.vision.value_objects import VisionDetectionResult


class VisionRecognizer(ABC):
    """Abstraction over a vision detection engine."""

    @abstractmethod
    async def detect(
        self,
        *,
        image: bytes,
        config: VisionRecognitionConfig,
    ) -> VisionDetectionResult:
        """Run detection on a single image frame."""
        raise NotImplementedError
