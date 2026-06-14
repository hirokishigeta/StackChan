"""Dummy AgentGateway returning fixed replies.

Used as a test fixture and as an explicit no-network fallback. The real
provider is :class:`OpenAICompatibleGateway`; see ADR-0004 for how firmware's
xiaozhi-compatible messages are bridged to the design-spec §11 API.
"""

from __future__ import annotations

from app.application.ports.agent_gateway import AgentGateway, ProgressCallback
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentAction, AgentReply, ProactiveEvent


class DummyAgentGateway(AgentGateway):
    """Returns canned responses regardless of input."""

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        return AgentReply(
            text="こんにちは、今日は何をしますか？",
            emotion="happy",
            actions=(AgentAction(type="set_expression", value="happy"),),
        )

    async def proactive(
        self,
        *,
        event: ProactiveEvent,
        profile: AgentProfile,
    ) -> AgentReply:
        return AgentReply(
            text="なにか手伝おうか？",
            emotion="curious",
            actions=(
                AgentAction(type="set_expression", value="curious"),
                AgentAction(type="proactive_speak", value=event.event_type),
            ),
        )
