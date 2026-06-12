"""Provider -> concrete AudioDecoder resolution via a registry.

Same pattern as the agent registry: a builder per provider + one map entry, no
``if``/``elif`` chains (CLAUDE.md). Selected by ``STACKCHAN_AUDIO_DECODER``.
Default is ``raw`` (PCM pass-through) so the server runs without libopus; set
``opus`` once the optional ``[opus]`` extra is installed.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.audio_decoder import AudioDecoder
from app.config.settings import AppSettings

from .opus_audio_decoder import OpusAudioDecoder
from .raw_pcm_audio_decoder import RawPcmAudioDecoder

DecoderBuilder = Callable[[AppSettings], AudioDecoder]


def _build_raw(settings: AppSettings) -> AudioDecoder:
    return RawPcmAudioDecoder()


def _build_opus(settings: AppSettings) -> AudioDecoder:
    # Construction is cheap and does not import libopus; the native binding is
    # resolved lazily on first decode (see OpusAudioDecoder).
    return OpusAudioDecoder()


_BUILDERS: dict[str, DecoderBuilder] = {
    "raw": _build_raw,
    "opus": _build_opus,
}

_DEFAULT = "raw"


def build_audio_decoder(settings: AppSettings) -> AudioDecoder:
    """Resolve and construct the configured uplink audio decoder."""
    builder = _BUILDERS.get(settings.audio_decoder, _BUILDERS[_DEFAULT])
    return builder(settings)
