"""Dummy VisionRecognizer returning a fixed detection.

TODO(issue#6/#8): replace with OpenCV / ONNX face & motion detectors and
head-pose / gaze estimation for attention detection (design-spec §5 / §6).
"""

from __future__ import annotations

from app.application.ports.vision_recognizer import VisionRecognizer
from app.domain.vision.entities import VisionRecognitionConfig
from app.domain.vision.value_objects import (
    BoundingBox,
    Detection,
    TrackingTarget,
    VisionDetectionResult,
)


class DummyVisionRecognizer(VisionRecognizer):
    """Returns a fixed single-face detection regardless of input."""

    async def detect(
        self,
        *,
        image: bytes,
        config: VisionRecognitionConfig,
    ) -> VisionDetectionResult:
        bbox = BoundingBox(x=120, y=80, width=64, height=64)
        return VisionDetectionResult(
            detections=(Detection(type="face", bbox=bbox, confidence=0.88),),
            tracking_target=TrackingTarget(x=152, y=112),
        )
