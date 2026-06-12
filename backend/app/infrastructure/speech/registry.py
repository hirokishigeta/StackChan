"""Provider -> concrete SpeechRecognizer resolution via a registry.

Mirrors the agent registry (CLAUDE.md: registry, not ``if`` branching).
Selected by ``STACKCHAN_DEFAULT_SPEECH_PROVIDER``. ``sherpa-onnx`` is the
default real provider; ``dummy`` is kept for tests / no-model environments.
Construction never loads native libs or models — those are lazy (see
:class:`SherpaOnnxSpeechRecognizer`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.speech_recognizer import SpeechRecognizer
from app.config.settings import AppSettings

from .dummy_speech_recognizer import DummySpeechRecognizer
from .sherpa_onnx_speech_recognizer import SherpaOnnxSpeechRecognizer

RecognizerBuilder = Callable[[AppSettings], SpeechRecognizer]


def _build_dummy(settings: AppSettings) -> SpeechRecognizer:
    return DummySpeechRecognizer()


def _build_sherpa(settings: AppSettings) -> SpeechRecognizer:
    return SherpaOnnxSpeechRecognizer(settings)


_BUILDERS: dict[str, RecognizerBuilder] = {
    "dummy": _build_dummy,
    "sherpa-onnx": _build_sherpa,
}

_DEFAULT = "sherpa-onnx"


def build_speech_recognizer(settings: AppSettings) -> SpeechRecognizer:
    """Resolve and construct the configured SpeechRecognizer."""
    builder = _BUILDERS.get(settings.default_speech_provider, _BUILDERS[_DEFAULT])
    return builder(settings)
