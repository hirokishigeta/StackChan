"""The single concrete-dependency resolution point (CLAUDE.md / design-spec §4.2).

Ports (ABCs) are bound to infrastructure concretes here only. No ``if``-based
provider switching: swapping a provider means changing the concrete wired
below (or adding an adapter and changing one binding).

Wiring is exposed as FastAPI dependencies so interfaces depend on the ABCs.
"""

from __future__ import annotations

from functools import lru_cache

from app.application.ports.agent_gateway import AgentGateway
from app.application.ports.bot_event_publisher import BotEventPublisher
from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.application.ports.vision_recognizer import VisionRecognizer
from app.application.ports.wakeword_detector import WakeWordDetector
from app.config.settings import AppSettings, get_settings
from app.infrastructure.agent.registry import build_agent_gateway
from app.infrastructure.persistence.sqlite_settings_repository import SqliteSettingsRepository
from app.infrastructure.speech.dummy_speech_recognizer import DummySpeechRecognizer
from app.infrastructure.transport.in_memory_bot_event_publisher import InMemoryBotEventPublisher
from app.infrastructure.vision.dummy_vision_recognizer import DummyVisionRecognizer
from app.infrastructure.wakeword.dummy_wakeword_detector import DummyWakeWordDetector


class Container:
    """Holds singleton instances of the wired concretes for one app."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._repository: SettingsRepository = SqliteSettingsRepository(settings.database_url)
        # Provider resolved via the registry (no if-branching); default is
        # OpenAICompatible (design-spec §11.3 / CLAUDE.md).
        self._agent_gateway: AgentGateway = build_agent_gateway(settings)
        self._speech_recognizer: SpeechRecognizer = DummySpeechRecognizer()
        self._vision_recognizer: VisionRecognizer = DummyVisionRecognizer()
        self._wakeword_detector: WakeWordDetector = DummyWakeWordDetector()
        self._event_publisher: BotEventPublisher = InMemoryBotEventPublisher()

    @property
    def repository(self) -> SettingsRepository:
        return self._repository

    @property
    def agent_gateway(self) -> AgentGateway:
        return self._agent_gateway

    @property
    def speech_recognizer(self) -> SpeechRecognizer:
        return self._speech_recognizer

    @property
    def vision_recognizer(self) -> VisionRecognizer:
        return self._vision_recognizer

    @property
    def wakeword_detector(self) -> WakeWordDetector:
        return self._wakeword_detector

    @property
    def event_publisher(self) -> BotEventPublisher:
        return self._event_publisher


@lru_cache
def get_container() -> Container:
    """Return the process-wide container (overridable in tests)."""
    return Container(get_settings())
