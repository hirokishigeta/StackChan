"""Provider -> concrete AudioEncoder resolution via a registry.

Same pattern as the decoder registry: a builder per provider + one map entry, no
``if``/``elif`` chains (CLAUDE.md). Selected by ``STACKCHAN_AUDIO_ENCODER``.
Default is ``raw`` (PCM pass-through, framed) so the downlink TTS path runs
without libopus; set ``opus`` once the optional ``[opus]`` extra is installed.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.audio_encoder import AudioEncoder
from app.config.settings import AppSettings

from .opus_audio_encoder import OpusAudioEncoder
from .raw_pcm_audio_encoder import RawPcmAudioEncoder

EncoderBuilder = Callable[[AppSettings], AudioEncoder]


def _build_raw(settings: AppSettings) -> AudioEncoder:
    return RawPcmAudioEncoder()


def _build_opus(settings: AppSettings) -> AudioEncoder:
    # Construction is cheap and does not import libopus; the native binding is
    # resolved lazily on first encode (see OpusAudioEncoder).
    return OpusAudioEncoder()


_BUILDERS: dict[str, EncoderBuilder] = {
    "raw": _build_raw,
    "opus": _build_opus,
}

_DEFAULT = "raw"


def build_audio_encoder(settings: AppSettings) -> AudioEncoder:
    """Resolve and construct the configured downlink audio encoder."""
    builder = _BUILDERS.get(settings.audio_encoder, _BUILDERS[_DEFAULT])
    return builder(settings)
