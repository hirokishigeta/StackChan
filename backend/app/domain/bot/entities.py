"""Bot entity (design-spec §4.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .value_objects import BotCapabilities, ConnectionStatus


@dataclass(frozen=True)
class Bot:
    """A registered CoreS3 AI Bot device.

    Immutable: state transitions produce a new instance via the ``with_*``
    helpers, keeping the domain free of mutation side effects.
    """

    device_id: str
    name: str
    firmware_version: str
    capabilities: BotCapabilities = field(default_factory=BotCapabilities)
    backend_url: str | None = None
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    current_expression: str = "neutral"
    last_seen_at: str | None = None

    def with_connection_status(self, status: ConnectionStatus) -> Bot:
        """Return a copy with an updated connection status."""
        return Bot(
            device_id=self.device_id,
            name=self.name,
            firmware_version=self.firmware_version,
            capabilities=self.capabilities,
            backend_url=self.backend_url,
            connection_status=status,
            current_expression=self.current_expression,
            last_seen_at=self.last_seen_at,
        )
