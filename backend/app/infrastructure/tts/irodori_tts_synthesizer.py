"""SpeechSynthesizer backed by Irodori-TTS (ADR-0006, optional heavy deps).

Irodori-TTS (Aratako/Irodori-TTS-500M) is a Japanese, diffusion-based TTS with
emoji-driven style control and zero-shot speaker cloning from a reference wav.
Its dependencies (PyTorch / HF checkpoint) are an *optional* extra (``pip
install 'stackchan-backend[tts]'``) and the model is a separate, large download.

Neither torch nor the model is imported/loaded at module import time, so the
process and ``make check`` stay green without them. The pipeline and model are
resolved lazily on first :meth:`synthesize`; a missing dependency or unset model
path raises :class:`SpeechSynthesisError` (which the WS loop turns into a
text-only fallback, design-spec §13) instead of crashing import.

Paths / device / sample rate come from :class:`AppSettings` (CLAUDE.md: no
hard-coded paths). The agent ``emotion`` is mapped to an Irodori emoji style via
:mod:`app.infrastructure.tts.emotion_style`.

TODO(issue#7b): the concrete pipeline call below is written against the
documented Irodori interface but cannot be exercised here without the model.
Wire/verify it on a GPU host with the checkpoint + reference wav present.
"""

from __future__ import annotations

import struct
from typing import Any

from app.application.ports.speech_synthesizer import SpeechSynthesisError, SpeechSynthesizer
from app.config.settings import AppSettings
from app.domain.speech.value_objects import SynthesizedAudio

from .emotion_style import style_text


class IrodoriTtsSynthesizer(SpeechSynthesizer):
    """Zero-shot Japanese TTS via Irodori-TTS (emoji style control)."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._pipeline: Any | None = None

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        try:
            import torch  # noqa: F401
            from irodori_tts import IrodoriTTS
        except ImportError as exc:  # pragma: no cover - optional heavy dep
            raise SpeechSynthesisError(
                "Irodori-TTS is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[tts]' (requires PyTorch)."
            ) from exc

        model_path = self._settings.irodori_model_path
        if not model_path:
            raise SpeechSynthesisError(
                "Irodori-TTS model path is not configured. Set "
                "STACKCHAN_IRODORI_MODEL_PATH (ADR-0006)."
            )
        self._pipeline = IrodoriTTS.from_pretrained(
            model_path, device=self._settings.irodori_device
        )
        return self._pipeline

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        pipeline = self._load_pipeline()
        styled = style_text(text=text, emotion=emotion)
        reference = self._settings.irodori_reference_wav_path or None
        try:
            # Irodori returns a float waveform at irodori_sample_rate (48 kHz).
            waveform = pipeline.synthesize(styled, reference_wav=reference)
        except Exception as exc:  # noqa: BLE001 - normalize engine errors
            raise SpeechSynthesisError(f"Irodori-TTS synthesis failed: {exc}") from exc
        pcm = self._float_to_pcm16(waveform)
        return SynthesizedAudio(pcm=pcm, sample_rate=self._settings.irodori_sample_rate)

    @staticmethod
    def _float_to_pcm16(waveform: Any) -> bytes:
        """Convert a float waveform (list / numpy / torch tensor) to PCM16 bytes."""
        try:
            samples = waveform.tolist()  # numpy / torch
        except AttributeError:
            samples = list(waveform)
        flat: list[float] = _flatten(samples)
        ints = [max(-32768, min(32767, round(float(s) * 32767.0))) for s in flat]
        return struct.pack(f"<{len(ints)}h", *ints)


def _flatten(values: Any) -> list[float]:
    if isinstance(values, (list, tuple)):
        out: list[float] = []
        for v in values:
            out.extend(_flatten(v))
        return out
    return [values]
