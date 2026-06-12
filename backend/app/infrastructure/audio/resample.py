"""Linear PCM16 resampling (no native dependency).

The downlink TTS path produces audio at the engine's rate (Irodori-TTS emits
48 kHz, ADR-0006) and must hand the Opus encoder PCM at the negotiated downlink
rate (default 24 kHz, docs/backend-protocol.md §3). A small dependency-free
linear resampler keeps ``make check`` green without pulling in scipy/soxr; a
higher-quality resampler can be swapped behind the same function later.
"""

from __future__ import annotations

import struct


def resample_pcm16(*, pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample little-endian PCM16 mono from ``src_rate`` to ``dst_rate``.

    Uses linear interpolation. Returns the input unchanged when the rates match
    or when there is nothing to resample.
    """
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("sample rates must be positive")
    if src_rate == dst_rate:
        return pcm
    src_count = len(pcm) // 2
    if src_count == 0:
        return b""
    samples = struct.unpack(f"<{src_count}h", pcm[: src_count * 2])
    if src_count == 1:
        return struct.pack("<h", samples[0])
    dst_count = max(1, round(src_count * dst_rate / src_rate))
    ratio = (src_count - 1) / (dst_count - 1) if dst_count > 1 else 0.0
    out: list[int] = []
    for i in range(dst_count):
        pos = i * ratio
        left = int(pos)
        frac = pos - left
        right = min(left + 1, src_count - 1)
        value = samples[left] + (samples[right] - samples[left]) * frac
        out.append(_clamp_int16(round(value)))
    return struct.pack(f"<{dst_count}h", *out)


def _clamp_int16(value: int) -> int:
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return value
