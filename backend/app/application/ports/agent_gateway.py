"""Agent gateway port (ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply


class AgentGateway(ABC):
    """Abstraction over an agent backend (design-spec §4.3).

    Concrete adapters (HermesAgent / OpenClaw / OpenAICompatible) live in
    ``infrastructure/agent`` and are wired in ``di_container``.
    """

    @abstractmethod
    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
    ) -> AgentReply:
        """Run one agent turn and return its reply."""
        raise NotImplementedError
