"""Agent gateway port (ABC) and its error type."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent


class AgentError(RuntimeError):
    """Raised when an agent backend fails (timeout / connection / bad response).

    Adapters wrap provider-specific failures (httpx errors, malformed payloads)
    in this type so callers can degrade gracefully instead of leaking transport
    details. The conversation loop must not break on a single failed turn
    (design-spec §13 stability).
    """


class AgentGateway(ABC):
    """Abstraction over an agent backend (design-spec §4.3).

    Concrete adapters (HermesAgent / OpenClaw / OpenAICompatible) live in
    ``infrastructure/agent`` and are wired in ``di_container``. Implementations
    must raise :class:`AgentError` (not transport-specific exceptions) on
    failure.
    """

    @abstractmethod
    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
    ) -> AgentReply:
        """Run one user-driven agent turn and return its reply (§11.3)."""
        raise NotImplementedError

    @abstractmethod
    async def proactive(
        self,
        *,
        event: ProactiveEvent,
        profile: AgentProfile,
    ) -> AgentReply:
        """Generate a proactive (event-driven) utterance (§11.7).

        Triggered by device-side events such as ``attention_detected``. The
        reply is expected to carry a ``proactive_speak`` action.
        """
        raise NotImplementedError
