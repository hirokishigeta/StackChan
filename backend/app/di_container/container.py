"""The single concrete-dependency resolution point (CLAUDE.md / design-spec §4.2).

Ports (ABCs) are bound to infrastructure concretes here only. No ``if``-based
provider switching: swapping a provider means changing the concrete wired
below (or adding an adapter and changing one binding).

Wiring is exposed as FastAPI dependencies so interfaces depend on the ABCs.
"""

from __future__ import annotations

from functools import lru_cache

from app.application.ports.agent_gateway import AgentGateway
from app.application.ports.audio_decoder import AudioDecoder
from app.application.ports.audio_encoder import AudioEncoder
from app.application.ports.bot_event_publisher import BotEventPublisher
from app.application.ports.server_settings_repository import ServerSettingsRepository
from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.application.ports.vision_recognizer import VisionRecognizer
from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.application.ports.wakeword_detector import WakeWordDetector
from app.application.use_cases.detect_attention import SessionStore
from app.application.use_cases.manage_server_settings import ManageServerSettingsUseCase
from app.config.settings import AppSettings, get_settings
from app.infrastructure.agent.registry import build_agent_gateway
from app.infrastructure.audio.encoder_registry import build_audio_encoder
from app.infrastructure.audio.registry import build_audio_decoder
from app.infrastructure.persistence.filesystem_voice_sample_repository import (
    FilesystemVoiceSampleRepository,
)
from app.infrastructure.persistence.sqlite_server_settings_repository import (
    SqliteServerSettingsRepository,
)
from app.infrastructure.persistence.sqlite_settings_repository import SqliteSettingsRepository
from app.infrastructure.speech.registry import build_speech_recognizer
from app.infrastructure.transport.in_memory_bot_event_publisher import InMemoryBotEventPublisher
from app.infrastructure.tts.registry import build_speech_synthesizer
from app.infrastructure.vision.registry import build_vision_recognizer
from app.infrastructure.wakeword.dummy_wakeword_detector import DummyWakeWordDetector


class Container:
    """Holds singleton instances of the wired concretes for one app."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._repository: SettingsRepository = SqliteSettingsRepository(settings.database_url)
        # Server-global runtime voice (TTS) settings: persisted dashboard
        # override layered onto env defaults (ADR-0009). The use case doubles as
        # the VoiceConfigProvider the synthesizer reads per-call.
        self._server_settings_repository: ServerSettingsRepository = SqliteServerSettingsRepository(
            settings.database_url
        )
        # Pre-generated reference voices listed from STACKCHAN_VOICE_SAMPLES_DIR
        # (ADR-0012). Selecting one fixes the cloned TTS timbre.
        self._voice_sample_repository: VoiceSampleRepository = FilesystemVoiceSampleRepository(
            settings.voice_samples_dir
        )
        self._server_settings_use_case = ManageServerSettingsUseCase(
            self._server_settings_repository, settings, self._voice_sample_repository
        )
        # Provider resolved via the registry (no if-branching); default is
        # OpenAICompatible (design-spec §11.3 / CLAUDE.md).
        self._agent_gateway: AgentGateway = build_agent_gateway(settings)
        # Provider resolved via the speech registry (sherpa-onnx default; dummy
        # kept for tests / no-model environments). No if-branching.
        self._speech_recognizer: SpeechRecognizer = build_speech_recognizer(settings)
        # Uplink Opus decoder resolved via the audio registry (raw default).
        self._audio_decoder: AudioDecoder = build_audio_decoder(settings)
        # Downlink TTS: synthesizer (dummy default; irodori in deployment,
        # ADR-0006) + Opus encoder (raw default). Both registry-resolved, no
        # if-branching; heavy deps stay lazy (#7-b).
        self._speech_synthesizer: SpeechSynthesizer = build_speech_synthesizer(
            settings, self._server_settings_use_case
        )
        self._audio_encoder: AudioEncoder = build_audio_encoder(settings)
        # Provider resolved via the vision registry (dummy default; opencv in
        # deployment with the optional [vision] extra). No if-branching. The
        # OpenCV adapter loads cv2 / the cascade lazily (#8).
        self._vision_recognizer: VisionRecognizer = build_vision_recognizer(settings)
        self._wakeword_detector: WakeWordDetector = DummyWakeWordDetector()
        self._event_publisher: BotEventPublisher = InMemoryBotEventPublisher()
        # Per-device vision/attention runtime state (VisionState, attention
        # continuity, proactive-talk cooldown / daily cap). In-memory this phase.
        self._vision_sessions: SessionStore = SessionStore()

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def repository(self) -> SettingsRepository:
        return self._repository

    @property
    def server_settings_repository(self) -> ServerSettingsRepository:
        return self._server_settings_repository

    @property
    def voice_sample_repository(self) -> VoiceSampleRepository:
        return self._voice_sample_repository

    @property
    def server_settings_use_case(self) -> ManageServerSettingsUseCase:
        return self._server_settings_use_case

    @property
    def agent_gateway(self) -> AgentGateway:
        return self._agent_gateway

    @property
    def speech_recognizer(self) -> SpeechRecognizer:
        return self._speech_recognizer

    @property
    def audio_decoder(self) -> AudioDecoder:
        return self._audio_decoder

    @property
    def speech_synthesizer(self) -> SpeechSynthesizer:
        return self._speech_synthesizer

    @property
    def audio_encoder(self) -> AudioEncoder:
        return self._audio_encoder

    @property
    def vision_recognizer(self) -> VisionRecognizer:
        return self._vision_recognizer

    @property
    def vision_sessions(self) -> SessionStore:
        return self._vision_sessions

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
