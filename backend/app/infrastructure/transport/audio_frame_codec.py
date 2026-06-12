"""xiaozhi binary audio frame (un)packing (docs/backend-protocol.md §3.1).

The device negotiates a binary frame ``version`` in its ``hello``:

- version 2 (``BinaryProtocol2``, network byte order, packed):
  ``version(u16) | type(u16, 0=OPUS) | reserved(u32) | timestamp(u32) |
  payload_size(u32) | payload[]``
- version 3 (``BinaryProtocol3``, packed):
  ``type(u8, 0=OPUS) | reserved(u8) | payload_size(u16) | payload[]``
- otherwise (version unset / 0): raw Opus payload (no header).

Only *uplink* decoding (frame -> payload) is needed for #7-a; downlink encoding
(#7-b TTS) reuses :func:`encode_frame`, kept here so #5 can rely on a single
codec. The Opus payload returned by :func:`decode_frame` is handed to the
:class:`~app.application.ports.audio_decoder.AudioDecoder`.
"""

from __future__ import annotations

import struct

_OPUS_TYPE = 0
_V2_HEADER = struct.Struct("!HHIII")  # version, type, reserved, timestamp, size
_V3_HEADER = struct.Struct("!BBH")  # type, reserved, size


class AudioFrameError(ValueError):
    """Raised when a binary frame is malformed for the negotiated version."""


def decode_frame(*, data: bytes, version: int) -> bytes:
    """Extract the Opus payload from one binary frame for ``version``."""
    if version == 2:
        if len(data) < _V2_HEADER.size:
            raise AudioFrameError("frame shorter than v2 header")
        _, _type, _reserved, _timestamp, size = _V2_HEADER.unpack_from(data, 0)
        payload = data[_V2_HEADER.size : _V2_HEADER.size + size]
        if len(payload) != size:
            raise AudioFrameError("v2 payload size mismatch")
        return payload
    if version == 3:
        if len(data) < _V3_HEADER.size:
            raise AudioFrameError("frame shorter than v3 header")
        _type, _reserved, size = _V3_HEADER.unpack_from(data, 0)
        payload = data[_V3_HEADER.size : _V3_HEADER.size + size]
        if len(payload) != size:
            raise AudioFrameError("v3 payload size mismatch")
        return payload
    # Raw Opus (no header).
    return data


def encode_frame(*, payload: bytes, version: int, timestamp: int = 0) -> bytes:
    """Wrap an Opus payload into a binary frame for ``version`` (downlink, #7-b)."""
    if version == 2:
        return _V2_HEADER.pack(2, _OPUS_TYPE, 0, timestamp, len(payload)) + payload
    if version == 3:
        return _V3_HEADER.pack(_OPUS_TYPE, 0, len(payload)) + payload
    return payload
