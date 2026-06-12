"""Audio encoder port (ABC) for downlink TTS audio (Issue #7-b).

The WebSocket audio server resamples synthesized PCM to the negotiated downlink
rate (default 24 kHz / mono / 60 ms, see ``docs/backend-protocol.md`` §3) and
encodes it into Opus frames before wrapping them with the binary frame codec.
The concrete codec (libopus binding) is an *optional* native dependency, so the
WS handler depends only on this abstraction (CLAUDE.md: ports = ABC,
infrastructure = concrete). Tests inject a fake.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.value_objects import AudioFormat


class AudioEncodeError(RuntimeError):
    """Raised when PCM cannot be encoded (bad input / missing codec).

    The WS loop catches this and falls back to a text-only turn (design-spec
    §13): a missing codec must not tear down the session.
    """


class AudioEncoder(ABC):
    """Abstraction over a downlink audio codec (PCM16 -> Opus frames)."""

    def for_session(self) -> AudioEncoder:
        """Return an encoder instance scoped to a single WS session.

        Stateful codecs (libopus) keep per-stream state, so each connection
        must own its own encoder — sharing one across concurrent sessions
        interleaves frames from different streams and corrupts the output
        (Issue #27). Stateless implementations (raw pass-through, test fakes)
        override nothing and safely return ``self``; stateful ones return a
        fresh instance. The WS handler calls this once at connection start.
        """
        return self

    @abstractmethod
    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        """Encode little-endian PCM16 mono into a list of Opus frame payloads.

        ``audio_format`` carries the negotiated downlink sample rate / channels /
        frame duration; the PCM must already be at that sample rate. One payload
        is produced per ``frame_duration_ms`` window. Implementations raise
        :class:`AudioEncodeError` on failure rather than leaking codec-specific
        exceptions.
        """
        raise NotImplementedError
