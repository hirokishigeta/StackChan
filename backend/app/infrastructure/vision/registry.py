"""Provider -> concrete VisionRecognizer resolution via a registry.

Mirrors the speech / tts / audio registries (CLAUDE.md: registry, not ``if``
branching). Selected by ``STACKCHAN_DEFAULT_VISION_PROVIDER``. ``dummy`` is the
default so the process and ``make check`` run without OpenCV or any model; set
``opencv`` once the optional ``[vision]`` extra is installed. Construction never
imports cv2 or loads a cascade — those are lazy (see :class:`OpenCvFaceDetector`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.vision_recognizer import VisionRecognizer
from app.config.settings import AppSettings

from .dummy_vision_recognizer import DummyVisionRecognizer
from .opencv_face_detector import OpenCvFaceDetector

RecognizerBuilder = Callable[[AppSettings], VisionRecognizer]


def _build_dummy(settings: AppSettings) -> VisionRecognizer:
    return DummyVisionRecognizer()


def _build_opencv(settings: AppSettings) -> VisionRecognizer:
    return OpenCvFaceDetector(settings)


_BUILDERS: dict[str, RecognizerBuilder] = {
    "dummy": _build_dummy,
    "opencv": _build_opencv,
}

_DEFAULT = "dummy"


def build_vision_recognizer(settings: AppSettings) -> VisionRecognizer:
    """Resolve and construct the configured VisionRecognizer."""
    builder = _BUILDERS.get(settings.default_vision_provider, _BUILDERS[_DEFAULT])
    return builder(settings)
