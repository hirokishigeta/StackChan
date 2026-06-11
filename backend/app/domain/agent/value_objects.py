"""Agent value objects (design-spec §4.4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentType(StrEnum):
    """Supported agent backends (Adapter is selected in di_container)."""

    HERMES_AGENT = "HermesAgent"
    OPEN_CLAW = "OpenClaw"
    OPENAI_COMPATIBLE = "OpenAICompatible"


class ResponseMode(StrEnum):
    """How the agent returns its response."""

    SYNC = "sync"
    STREAM = "stream"


@dataclass(frozen=True)
class AgentAction:
    """A single action returned alongside an agent reply (design-spec §11.3)."""

    type: str
    value: str | None = None


@dataclass(frozen=True)
class AgentReply:
    """The result of an agent turn."""

    text: str
    emotion: str = "neutral"
    actions: tuple[AgentAction, ...] = ()
