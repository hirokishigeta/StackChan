"""Bot value objects. Immutable, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Connection state of a Bot device."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


@dataclass(frozen=True)
class BotCapabilities:
    """Hardware capabilities reported by a Bot at registration time."""

    microphone: bool = True
    speaker: bool = True
    camera: bool = True
    display: bool = True
    touch: bool = True
    wake_word: bool = True


@dataclass(frozen=True)
class BotCommand:
    """A control command sent from backend to the CoreS3 device.

    See design-spec §11.5 for the command catalogue (``look_at``,
    ``set_expression``, ``proactive_speak``, ``start_tracking``,
    ``stop_tracking``).
    """

    type: str
    payload: dict[str, object]
