"""Bot domain services (pure logic, no external dependencies)."""

from __future__ import annotations

from .entities import Bot
from .value_objects import ConnectionStatus


def register_bot(
    device_id: str,
    firmware_version: str,
    *,
    name: str | None = None,
    capabilities_present: bool = True,
) -> Bot:
    """Create a freshly registered Bot in the connected state.

    ``name`` defaults to the device id when not provided.
    """
    return Bot(
        device_id=device_id,
        name=name or device_id,
        firmware_version=firmware_version,
        connection_status=ConnectionStatus.CONNECTED,
    )
