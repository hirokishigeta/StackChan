"""Agent entities (design-spec §4.4)."""

from __future__ import annotations

from dataclasses import dataclass

from .value_objects import AgentType, ResponseMode


@dataclass(frozen=True)
class AgentProfile:
    """Configuration of the agent backend for a Bot."""

    agent_type: AgentType = AgentType.OPENAI_COMPATIBLE
    model_name: str = "dummy-model"
    system_prompt: str = ""
    tools_enabled: bool = False
    memory_enabled: bool = False
    temperature: float = 0.7
    max_tokens: int = 512
    response_mode: ResponseMode = ResponseMode.SYNC
