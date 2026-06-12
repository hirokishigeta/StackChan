"""Provider -> concrete SpeechSynthesizer resolution via a registry.

Mirrors the speech/audio registries (CLAUDE.md: registry, not ``if`` branching).
Selected by ``STACKCHAN_DEFAULT_TTS_PROVIDER``. ``irodori`` is the real provider
(ADR-0006); ``dummy`` is the default for tests / no-model environments so the
process and ``make check`` run without heavy deps. Construction never loads
torch or models — those are lazy (see :class:`IrodoriTtsSynthesizer`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.config.settings import AppSettings

from .dummy_speech_synthesizer import DummySpeechSynthesizer
from .irodori_tts_synthesizer import IrodoriTtsSynthesizer

SynthesizerBuilder = Callable[[AppSettings], SpeechSynthesizer]


def _build_dummy(settings: AppSettings) -> SpeechSynthesizer:
    return DummySpeechSynthesizer(settings)


def _build_irodori(settings: AppSettings) -> SpeechSynthesizer:
    return IrodoriTtsSynthesizer(settings)


_BUILDERS: dict[str, SynthesizerBuilder] = {
    "dummy": _build_dummy,
    "irodori": _build_irodori,
}

_DEFAULT = "dummy"


def build_speech_synthesizer(settings: AppSettings) -> SpeechSynthesizer:
    """Resolve and construct the configured downlink SpeechSynthesizer."""
    builder = _BUILDERS.get(settings.default_tts_provider, _BUILDERS[_DEFAULT])
    return builder(settings)
