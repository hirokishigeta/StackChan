"""Opus -> PCM16 decoder backed by ``opuslib`` (optional native dependency).

``opuslib`` (and libopus) is an optional extra (``pip install
'stackchan-backend[opus]'``). It is **not** imported at module load time so the
process — and ``make check`` — stays green on machines without libopus. The
binding is resolved lazily on first :meth:`decode`; if it is missing the call
raises :class:`AudioDecodeError` with an actionable message instead of crashing
import (docs/backend-protocol.md §3.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.ports.audio_decoder import AudioDecodeError, AudioDecoder
from app.domain.speech.value_objects import AudioFormat

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable


class OpusAudioDecoder(AudioDecoder):
    """Decode Opus frames to little-endian PCM16 mono via libopus.

    A decoder is created per (sample_rate, channels) and cached, since libopus
    decoders are stateful and tied to those parameters.
    """

    def __init__(self) -> None:
        self._decoders: dict[tuple[int, int], Any] = {}
        self._decoder_cls: Callable[..., Any] | None = None

    def _resolve_decoder_cls(self) -> Callable[..., Any]:
        if self._decoder_cls is not None:
            return self._decoder_cls
        try:
            from opuslib import Decoder
        except ImportError as exc:  # pragma: no cover - depends on optional native dep
            raise AudioDecodeError(
                "Opus support is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[opus]' (requires libopus)."
            ) from exc
        decoder_cls: Callable[..., Any] = Decoder
        self._decoder_cls = decoder_cls
        return decoder_cls

    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        decoder_cls = self._resolve_decoder_cls()
        key = (audio_format.sample_rate, audio_format.channels)
        decoder = self._decoders.get(key)
        if decoder is None:
            decoder = decoder_cls(audio_format.sample_rate, audio_format.channels)
            self._decoders[key] = decoder
        frame_size = audio_format.sample_rate * audio_format.frame_duration_ms // 1000
        try:
            pcm = decoder.decode(payload, frame_size)
        except Exception as exc:  # noqa: BLE001 - normalize codec errors
            raise AudioDecodeError(f"failed to decode Opus frame: {exc}") from exc
        return bytes(pcm)
