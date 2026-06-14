"""OpenClaw AgentGateway adapter — stub.

TODO(issue#6): implement the real OpenClaw transport (per ADR-0004, bridge its
message schema to the design-spec §11 AgentReply shape). For now this is a
registered, swappable placeholder returning a minimal fixed reply so the
provider can be selected without a hard failure; the wiring/contract is in
place and only the transport is missing.
"""

from __future__ import annotations

from app.application.ports.agent_gateway import AgentGateway, ProgressCallback
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentAction, AgentReply, ProactiveEvent

# Stable marker so callers/tests can tell a stub reply from a real one.
_STUB_NOTICE = "[OpenClaw stub] not yet implemented (TODO issue#6)"


class OpenClawGateway(AgentGateway):
    """Placeholder adapter for the OpenClaw backend."""

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        return AgentReply(
            text=_STUB_NOTICE,
            emotion="neutral",
            actions=(AgentAction(type="set_expression", value="neutral"),),
        )

    async def proactive(
        self,
        *,
        event: ProactiveEvent,
        profile: AgentProfile,
    ) -> AgentReply:
        return AgentReply(
            text=_STUB_NOTICE,
            emotion="neutral",
            actions=(AgentAction(type="proactive_speak", value=event.event_type),),
        )
