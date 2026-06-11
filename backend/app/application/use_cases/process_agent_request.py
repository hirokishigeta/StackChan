"""Use case: run an agent turn for a Bot."""

from __future__ import annotations

from app.application.ports.agent_gateway import AgentGateway
from app.application.ports.settings_repository import SettingsRepository
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply


class ProcessAgentRequestUseCase:
    """Resolve the Bot's agent profile and delegate to the agent gateway."""

    def __init__(self, gateway: AgentGateway, repository: SettingsRepository) -> None:
        self._gateway = gateway
        self._repository = repository

    async def execute(
        self,
        *,
        device_id: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> AgentReply:
        """Run the agent turn using the device's stored profile (or defaults)."""
        settings = self._repository.get_settings(device_id)
        profile = settings.agent if settings is not None else AgentProfile()
        return await self._gateway.chat(message=message, profile=profile, context=context)
