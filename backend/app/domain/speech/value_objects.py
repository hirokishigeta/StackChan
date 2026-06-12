"""Speech recognition value objects (design-spec §4.4 / §11.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechRecognitionResult:
    """Outcome of a speech-to-text recognition."""

    text: str
    language: str
    confidence: float


@dataclass(frozen=True)
class AudioFormat:
    """Negotiated audio frame parameters (docs/backend-protocol.md §3).

    Uplink default is Opus / 16 kHz / mono / 60 ms; the client ``hello`` may
    override these (``audio_params``). Used by the audio decoder and binary
    frame codec.
    """

    codec: str = "opus"
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 60
