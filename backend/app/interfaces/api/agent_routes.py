"""Agent routes (design-spec §11.3 chat / §11.7 proactive talk).

On agent-backend failure (timeout / connection / bad response) we do NOT
return 5xx: the firmware conversation loop must survive a failed turn
(design-spec §13 stability). Instead we map :class:`AgentError` to a safe
fallback reply so the device can keep going.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.ports.agent_gateway import AgentError
from app.application.use_cases.process_agent_request import ProcessAgentRequestUseCase
from app.di_container.dependencies import get_agent_use_case
from app.domain.agent.value_objects import AgentAction, AgentReply

from .schemas import (
    AgentActionSchema,
    AgentChatRequest,
    AgentChatResponse,
    AgentProactiveRequest,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

_logger = logging.getLogger(__name__)

# Safe fallback when the agent backend fails (§13). Neutral, non-disruptive.
_FALLBACK_TEXT = "ごめんね、いまうまく考えられないみたい。もう一度話しかけてね。"


def _fallback_reply() -> AgentReply:
    return AgentReply(
        text=_FALLBACK_TEXT,
        emotion="sad",
        actions=(AgentAction(type="set_expression", value="sad"),),
    )


def _to_response(reply: AgentReply) -> AgentChatResponse:
    return AgentChatResponse(
        text=reply.text,
        emotion=reply.emotion,
        actions=[AgentActionSchema(type=a.type, value=a.value) for a in reply.actions],
    )


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    request: AgentChatRequest,
    use_case: Annotated[ProcessAgentRequestUseCase, Depends(get_agent_use_case)],
) -> AgentChatResponse:
    """Run one agent turn (design-spec §11.3)."""
    try:
        reply = await use_case.execute(
            device_id=request.device_id,
            message=request.message,
            context=request.context,
        )
    except AgentError:
        _logger.warning("agent chat failed for %s; returning fallback", request.device_id)
        reply = _fallback_reply()
    return _to_response(reply)


@router.post("/proactive", response_model=AgentChatResponse)
async def proactive(
    request: AgentProactiveRequest,
    use_case: Annotated[ProcessAgentRequestUseCase, Depends(get_agent_use_case)],
) -> AgentChatResponse:
    """Generate a proactive utterance from a device event (design-spec §11.7)."""
    try:
        reply = await use_case.execute_proactive(
            device_id=request.device_id,
            event_type=request.event_type,
            context=request.context,
        )
    except AgentError:
        _logger.warning("agent proactive failed for %s; returning fallback", request.device_id)
        reply = _fallback_reply()
    return _to_response(reply)
