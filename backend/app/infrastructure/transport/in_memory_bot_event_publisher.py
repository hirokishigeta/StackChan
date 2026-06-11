"""In-memory BotEventPublisher (stand-in for a WebSocket transport).

Buffers commands per device so the polling endpoint
``GET /api/bot/{device_id}/commands`` (design-spec §11.5) can drain them.

TODO(issue#8): replace with a WebSocket-based publisher
(``websocket_bot_event_publisher``) per design-spec §11.8.
"""

from __future__ import annotations

from collections import defaultdict

from app.application.ports.bot_event_publisher import BotEventPublisher
from app.domain.bot.value_objects import BotCommand


class InMemoryBotEventPublisher(BotEventPublisher):
    """Queues commands per device in memory."""

    def __init__(self) -> None:
        self._queues: dict[str, list[BotCommand]] = defaultdict(list)

    async def publish_command(self, *, device_id: str, command: BotCommand) -> None:
        self._queues[device_id].append(command)

    def drain(self, device_id: str) -> list[BotCommand]:
        """Return and clear the buffered commands for a device."""
        commands = self._queues.get(device_id, [])
        self._queues[device_id] = []
        return commands
