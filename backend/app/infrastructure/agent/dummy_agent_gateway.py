"""Dummy AgentGateway returning a fixed reply.

TODO(issue#6): replace with real OpenAI-compatible / HermesAgent / OpenClaw
adapters. Per ADR-0004, firmware speaks the xiaozhi-compatible message
schema; the backend exposes the design-spec §11 API and an adapter bridges
the two.
"""

from __future__ import annotations

from app.application.ports.agent_gateway import AgentGateway
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentAction, AgentReply


class DummyAgentGateway(AgentGateway):
    """Returns a canned response regardless of input."""

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
    ) -> AgentReply:
        return AgentReply(
            text="こんにちは、今日は何をしますか？",
            emotion="happy",
            actions=(AgentAction(type="set_expression", value="happy"),),
        )
