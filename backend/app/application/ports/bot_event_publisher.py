"""Bot event publisher port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.bot.value_objects import BotCommand


class BotEventPublisher(ABC):
    """Abstraction over pushing control commands / events to a Bot.

    Concrete transport (e.g. WebSocket) lives in ``infrastructure/transport``.
    """

    @abstractmethod
    async def publish_command(self, *, device_id: str, command: BotCommand) -> None:
        """Publish a single control command to the target device."""
        raise NotImplementedError
