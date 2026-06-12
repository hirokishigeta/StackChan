"""Pass-through decoder that treats payloads as already-PCM bytes.

Default wiring when Opus is not configured/installed: it lets the WS server and
its tests run end-to-end without a native codec (the fake firmware client sends
raw PCM). Real Opus decoding uses :class:`OpusAudioDecoder` once the optional
``opus`` extra is installed and ``STACKCHAN_AUDIO_DECODER=opus`` is set.
"""

from __future__ import annotations

from app.application.ports.audio_decoder import AudioDecoder
from app.domain.speech.value_objects import AudioFormat


class RawPcmAudioDecoder(AudioDecoder):
    """Returns the payload unchanged (assumed PCM16 mono)."""

    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        return payload
