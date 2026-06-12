"""Pass-through encoder that emits raw PCM as "frame payloads".

Default wiring when Opus is not configured/installed: it lets the WS server and
its tests exercise the downlink TTS path end-to-end without a native codec (the
fake firmware client just receives PCM-sized binary frames). Real Opus encoding
uses :class:`OpusAudioEncoder` once the optional ``opus`` extra is installed and
``STACKCHAN_AUDIO_ENCODER=opus`` is set.

The PCM is split into ``frame_duration_ms`` windows so the frame cadence matches
what the device expects (docs/backend-protocol.md §3).
"""

from __future__ import annotations

from app.application.ports.audio_encoder import AudioEncoder
from app.domain.speech.value_objects import AudioFormat


class RawPcmAudioEncoder(AudioEncoder):
    """Splits PCM16 mono into fixed-duration frames, returned unchanged."""

    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        samples_per_frame = audio_format.sample_rate * audio_format.frame_duration_ms // 1000
        bytes_per_frame = samples_per_frame * audio_format.channels * 2
        if bytes_per_frame <= 0:
            return [pcm] if pcm else []
        return [pcm[i : i + bytes_per_frame] for i in range(0, len(pcm), bytes_per_frame)]
