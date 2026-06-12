"""Deterministic, dependency-free SpeechSynthesizer for tests / no-model envs.

Default TTS wiring when Irodori is not configured/installed: produces a short
block of silence PCM (length scaled to the text) at a configurable sample rate,
so the downlink TTS path (resample -> encode -> binary frames) can run and be
tested end-to-end without PyTorch or a model (CLAUDE.md: external deps mocked).
Real synthesis uses :class:`IrodoriTtsSynthesizer` once the ``[tts]`` extra is
installed and ``STACKCHAN_DEFAULT_TTS_PROVIDER=irodori`` is set (ADR-0006).
"""

from __future__ import annotations

from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.config.settings import AppSettings
from app.domain.speech.value_objects import SynthesizedAudio

# ~20 ms of audio per character, capped, so a reply yields a few real frames.
_MS_PER_CHAR = 20
_MAX_MS = 2000


class DummySpeechSynthesizer(SpeechSynthesizer):
    """Returns silence PCM sized from the text, at the downlink sample rate."""

    def __init__(self, settings: AppSettings) -> None:
        self._sample_rate = settings.downlink_sample_rate

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        duration_ms = min(_MAX_MS, max(_MS_PER_CHAR, len(text) * _MS_PER_CHAR))
        sample_count = self._sample_rate * duration_ms // 1000
        return SynthesizedAudio(pcm=b"\x00\x00" * sample_count, sample_rate=self._sample_rate)
