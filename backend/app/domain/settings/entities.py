"""Settings aggregate (design-spec §4.4 / §10).

``BotSettings`` is the per-device aggregate persisted by the
``SettingsRepository`` port and exposed through the Settings API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.agent.entities import AgentProfile
from app.domain.speech.entities import ConversationTurnConfig, SpeechRecognitionConfig
from app.domain.vision.entities import (
    AttentionDetectionConfig,
    ProactiveTalkConfig,
    VisionRecognitionConfig,
    VisionStreamPolicy,
)
from app.domain.wakeword.entities import EndWordConfig, WakeWordConfig

from .value_objects import DisplaySettings


@dataclass(frozen=True)
class BotSettings:
    """Full AI-side settings for one Bot device."""

    device_id: str
    agent: AgentProfile = field(default_factory=AgentProfile)
    speech: SpeechRecognitionConfig = field(default_factory=SpeechRecognitionConfig)
    conversation_turn: ConversationTurnConfig = field(default_factory=ConversationTurnConfig)
    vision: VisionRecognitionConfig = field(default_factory=VisionRecognitionConfig)
    vision_stream: VisionStreamPolicy = field(default_factory=VisionStreamPolicy)
    attention: AttentionDetectionConfig = field(default_factory=AttentionDetectionConfig)
    proactive_talk: ProactiveTalkConfig = field(default_factory=ProactiveTalkConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    end_word: EndWordConfig = field(default_factory=EndWordConfig)
    display: DisplaySettings = field(default_factory=DisplaySettings)

    @classmethod
    def default(cls, device_id: str) -> BotSettings:
        """Return default settings for a newly registered device."""
        return cls(device_id=device_id)
