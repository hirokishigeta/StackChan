"""Agent chat route (design-spec §11.3). Dummy backend in this phase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.process_agent_request import ProcessAgentRequestUseCase
from app.di_container.dependencies import get_agent_use_case

from .schemas import AgentActionSchema, AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    request: AgentChatRequest,
    use_case: Annotated[ProcessAgentRequestUseCase, Depends(get_agent_use_case)],
) -> AgentChatResponse:
    """Run one agent turn (design-spec §11.3)."""
    reply = await use_case.execute(
        device_id=request.device_id,
        message=request.message,
        context=request.context,
    )
    return AgentChatResponse(
        text=reply.text,
        emotion=reply.emotion,
        actions=[AgentActionSchema(type=a.type, value=a.value) for a in reply.actions],
    )
