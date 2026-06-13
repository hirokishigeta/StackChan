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
    # True when the agent judges the conversation has naturally ended (the user
    # said goodbye / there is nothing left to do). The WS loop then stops the
    # device's auto-listen so it returns to idle until the next wake word
    # (design-spec §7: turn/conversation lifecycle).
    end_conversation: bool = False


@dataclass(frozen=True)
class ProactiveEvent:
    """A device-side event that may trigger a proactive utterance.

    Mirrors the §11.7 request body (event_type + context). ``attention_detected``
    is the primary trigger; future event types reuse the same shape.
    """

    event_type: str
    context: tuple[tuple[str, object], ...] = ()

    @classmethod
    def from_context(cls, *, event_type: str, context: dict[str, object] | None) -> ProactiveEvent:
        """Build an event, freezing the (mutable) context dict into a tuple."""
        items = tuple(sorted((context or {}).items()))
        return cls(event_type=event_type, context=items)

    def context_dict(self) -> dict[str, object]:
        """Return the context as a plain dict (for adapters / prompts)."""
        return dict(self.context)
