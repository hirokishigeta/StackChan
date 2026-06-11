"""Settings value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DisplaySettings:
    """Screen / device basic settings preserved on the device (design-spec §3.1)."""

    brightness: int = 80
    theme: str = "default"
    volume: int = 70
