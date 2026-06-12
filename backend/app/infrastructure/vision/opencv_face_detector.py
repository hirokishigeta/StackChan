"""VisionRecognizer backed by OpenCV face detection (optional native dep).

``opencv-python`` is an optional extra (``pip install
'stackchan-backend[vision]'``) and the Haar cascade / DNN model file is a
separate asset. Neither is imported/loaded at module import time, so the process
and ``make check`` stay green without them. OpenCV and the cascade are resolved
lazily on first :meth:`detect`; a missing binding or cascade path raises
:class:`OpenCvVisionError` (a clear error) instead of crashing import.

This phase uses a Haar cascade (``cv2.CascadeClassifier``) — robust, CPU-only,
no extra model download when using OpenCV's bundled cascades. The cascade path
comes from :class:`AppSettings` (CLAUDE.md: no hard-coded paths); empty means
"use OpenCV's bundled frontal-face cascade".

TODO(issue#6): add a DNN/ONNX detector adapter for higher accuracy and
landmark / head-pose / gaze estimation (design-spec §6.2 developed
implementation). TODO(issue#5): the device sends adaptive-rate frames
(design-spec §5); this adapter only consumes a single frame's bytes.
"""

from __future__ import annotations

from typing import Any

from app.application.ports.vision_recognizer import VisionRecognizer
from app.config.settings import AppSettings
from app.domain.vision.entities import VisionRecognitionConfig
from app.domain.vision.services import select_primary_face, tracking_target_for
from app.domain.vision.value_objects import (
    BoundingBox,
    Detection,
    VisionDetectionResult,
)


class OpenCvVisionError(RuntimeError):
    """Raised when OpenCV is unavailable or misconfigured."""


class OpenCvFaceDetector(VisionRecognizer):
    """Detects faces in a JPEG/encoded image using an OpenCV Haar cascade."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._cv2: Any | None = None
        self._cascade: Any | None = None

    def _load(self) -> tuple[Any, Any]:
        if self._cv2 is not None and self._cascade is not None:
            return self._cv2, self._cascade
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - optional native dep
            raise OpenCvVisionError(
                "OpenCV is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[vision]'."
            ) from exc

        cascade_path = self._settings.opencv_face_cascade_path or (
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            raise OpenCvVisionError(
                f"Failed to load Haar cascade from {cascade_path!r}. Set "
                "STACKCHAN_OPENCV_FACE_CASCADE_PATH to a valid cascade XML."
            )
        self._cv2 = cv2
        self._cascade = cascade
        return cv2, cascade

    async def detect(
        self,
        *,
        image: bytes,
        config: VisionRecognitionConfig,
    ) -> VisionDetectionResult:
        cv2, cascade = self._load()
        gray = self._decode_grayscale(cv2, image)
        if gray is None:
            return VisionDetectionResult()

        # detectMultiScale returns (x, y, w, h) rects. Haar gives no confidence;
        # report a fixed nominal score (TODO(issue#6): use a DNN for real scores).
        rects = cascade.detectMultiScale(
            gray,
            scaleFactor=self._settings.opencv_scale_factor,
            minNeighbors=self._settings.opencv_min_neighbors,
        )
        detections = tuple(
            Detection(
                type="face",
                bbox=BoundingBox(x=int(x), y=int(y), width=int(w), height=int(h)),
                confidence=0.9,
            )
            for (x, y, w, h) in rects
        )
        primary = select_primary_face(detections)
        target = tracking_target_for(primary) if primary is not None else None
        return VisionDetectionResult(detections=detections, tracking_target=target)

    @staticmethod
    def _decode_grayscale(cv2: Any, image: bytes) -> Any:
        import numpy as np

        if not image:
            return None
        buffer = np.frombuffer(image, dtype=np.uint8)
        decoded = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
        return decoded
