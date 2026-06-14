"""Agent gateway port (ABC) and its error type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent

# Called by a gateway with a short, human-readable status label (e.g.
# "🔧 Web検索を実行中…") while it works, so the caller can surface tool/thinking
# progress to the device mid-turn. Streaming gateways (Hermes) call it; others
# ignore it.
ProgressCallback = Callable[[str], Awaitable[None]]


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
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        """Run one user-driven agent turn and return its reply (§11.3).

        The gateway MAY call ``progress_cb`` with a short human-readable status
        label while working (e.g. while a tool is running). Non-streaming
        gateways ignore it.
        """
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
