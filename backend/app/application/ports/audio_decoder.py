"""Audio decoder port (ABC).

The WebSocket audio server receives uplink Opus frames (16 kHz / mono / 60 ms,
see ``docs/backend-protocol.md`` §3) and must turn them into PCM before feeding
the :class:`~app.application.ports.speech_recognizer.SpeechRecognizer`. The
concrete codec (libopus binding) is an *optional* native dependency, so the WS
handler depends only on this abstraction (CLAUDE.md: ports = ABC,
infrastructure = concrete). Tests inject a fake.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.value_objects import AudioFormat


class AudioDecodeError(RuntimeError):
    """Raised when a frame cannot be decoded (bad payload / missing codec).

    The WS loop catches this and keeps the connection alive (design-spec §13):
    a single corrupt frame must not tear down the session.
    """


class AudioDecoder(ABC):
    """Abstraction over an uplink audio codec (e.g. Opus -> PCM16)."""

    def for_session(self) -> AudioDecoder:
        """Return a decoder instance scoped to a single WS session.

        Stateful codecs (libopus) keep per-stream state, so each connection
        must own its own decoder — sharing one across concurrent sessions
        interleaves frames from different streams and corrupts the output
        (Issue #27). Stateless implementations (raw pass-through, test fakes)
        override nothing and safely return ``self``; stateful ones return a
        fresh instance. The WS handler calls this once at connection start.
        """
        return self

    @abstractmethod
    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        """Decode one encoded frame into little-endian PCM16 mono bytes.

        ``audio_format`` carries the negotiated sample rate / channels / frame
        duration (from the client ``hello``). Implementations raise
        :class:`AudioDecodeError` on failure rather than leaking codec-specific
        exceptions.
        """
        raise NotImplementedError
