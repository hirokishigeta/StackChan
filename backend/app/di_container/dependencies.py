"""FastAPI dependency providers built from the Container.

Interfaces import these; they return application use cases / ports so the
presentation layer never constructs concretes directly.
"""

from __future__ import annotations

from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.application.use_cases.detect_attention import DetectAttentionUseCase
from app.application.use_cases.generate_voice_sample import GenerateVoiceSampleUseCase
from app.application.use_cases.manage_server_settings import ManageServerSettingsUseCase
from app.application.use_cases.manage_settings import ManageSettingsUseCase
from app.application.use_cases.process_agent_request import ProcessAgentRequestUseCase
from app.application.use_cases.process_voice_input import ProcessVoiceInputUseCase
from app.application.use_cases.register_bot import RegisterBotUseCase
from app.application.use_cases.run_vision_detection import RunVisionDetectionUseCase
from app.infrastructure.transport.in_memory_bot_event_publisher import InMemoryBotEventPublisher

from .container import get_container


def get_repository() -> SettingsRepository:
    return get_container().repository


def get_register_bot_use_case() -> RegisterBotUseCase:
    return RegisterBotUseCase(get_container().repository)


def get_agent_use_case() -> ProcessAgentRequestUseCase:
    container = get_container()
    return ProcessAgentRequestUseCase(container.agent_gateway, container.repository)


def get_voice_use_case() -> ProcessVoiceInputUseCase:
    container = get_container()
    return ProcessVoiceInputUseCase(container.speech_recognizer, container.repository)


def get_vision_use_case() -> RunVisionDetectionUseCase:
    container = get_container()
    return RunVisionDetectionUseCase(container.vision_recognizer, container.repository)


def get_attention_use_case() -> DetectAttentionUseCase:
    container = get_container()
    return DetectAttentionUseCase(
        container.vision_recognizer,
        container.repository,
        container.agent_gateway,
        container.event_publisher,
        sessions=container.vision_sessions,
    )


def get_settings_use_case() -> ManageSettingsUseCase:
    return ManageSettingsUseCase(get_container().repository)


def get_server_settings_use_case() -> ManageServerSettingsUseCase:
    return get_container().server_settings_use_case


def get_voice_sample_repository() -> VoiceSampleRepository:
    return get_container().voice_sample_repository


def get_generate_voice_sample_use_case() -> GenerateVoiceSampleUseCase:
    container = get_container()
    return GenerateVoiceSampleUseCase(
        container.speech_synthesizer, container.voice_sample_repository
    )


def get_event_publisher() -> InMemoryBotEventPublisher:
    publisher = get_container().event_publisher
    assert isinstance(publisher, InMemoryBotEventPublisher)
    return publisher
