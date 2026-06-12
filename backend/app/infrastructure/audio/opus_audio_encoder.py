"""PCM16 -> Opus encoder backed by ``opuslib`` (optional native dependency).

``opuslib`` (and libopus) is an optional extra (``pip install
'stackchan-backend[opus]'``). It is **not** imported at module load time so the
process — and ``make check`` — stays green on machines without libopus. The
binding is resolved lazily on first :meth:`encode`; if it is missing the call
raises :class:`AudioEncodeError` with an actionable message instead of crashing
import (docs/backend-protocol.md §3.2). Mirrors :class:`OpusAudioDecoder`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.ports.audio_encoder import AudioEncodeError, AudioEncoder
from app.domain.speech.value_objects import AudioFormat

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable


class OpusAudioEncoder(AudioEncoder):
    """Encode PCM16 mono to Opus frames via libopus.

    An encoder is created per (sample_rate, channels) and cached, since libopus
    encoders are stateful and tied to those parameters.
    """

    def __init__(self) -> None:
        self._encoders: dict[tuple[int, int], Any] = {}
        self._encoder_cls: Callable[..., Any] | None = None
        self._application: Any | None = None

    def _resolve_encoder_cls(self) -> tuple[Callable[..., Any], Any]:
        if self._encoder_cls is not None:
            return self._encoder_cls, self._application
        try:
            from opuslib import APPLICATION_VOIP, Encoder
        except ImportError as exc:  # pragma: no cover - depends on optional native dep
            raise AudioEncodeError(
                "Opus support is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[opus]' (requires libopus)."
            ) from exc
        encoder_cls: Callable[..., Any] = Encoder
        self._encoder_cls = encoder_cls
        self._application = APPLICATION_VOIP
        return encoder_cls, APPLICATION_VOIP

    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        encoder_cls, application = self._resolve_encoder_cls()
        key = (audio_format.sample_rate, audio_format.channels)
        encoder = self._encoders.get(key)
        if encoder is None:
            encoder = encoder_cls(audio_format.sample_rate, audio_format.channels, application)
            self._encoders[key] = encoder
        samples_per_frame = audio_format.sample_rate * audio_format.frame_duration_ms // 1000
        bytes_per_frame = samples_per_frame * audio_format.channels * 2
        if bytes_per_frame <= 0:
            return []
        frames: list[bytes] = []
        try:
            for i in range(0, len(pcm), bytes_per_frame):
                chunk = pcm[i : i + bytes_per_frame]
                if len(chunk) < bytes_per_frame:
                    # libopus needs a whole frame; pad the tail with silence.
                    chunk = chunk + b"\x00" * (bytes_per_frame - len(chunk))
                frames.append(bytes(encoder.encode(chunk, samples_per_frame)))
        except Exception as exc:  # noqa: BLE001 - normalize codec errors
            raise AudioEncodeError(f"failed to encode Opus frame: {exc}") from exc
        return frames
