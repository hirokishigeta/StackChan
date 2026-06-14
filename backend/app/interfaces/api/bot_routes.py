"""Bot registration, command polling and wake word routes (design-spec §11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.application.use_cases.manage_settings import ManageSettingsUseCase
from app.application.use_cases.register_bot import RegisterBotUseCase
from app.di_container.dependencies import (
    get_event_publisher,
    get_register_bot_use_case,
    get_settings_use_case,
)
from app.domain.wakeword.services import resolve_active_wake_words
from app.infrastructure.persistence.serialization import settings_to_dict
from app.infrastructure.transport.in_memory_bot_event_publisher import InMemoryBotEventPublisher

from .schemas import (
    BotCommandsResponse,
    BotRegisterRequest,
    BotRegisterResponse,
    WakeWordEntrySchema,
    WakeWordResponse,
)

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.post("/register", response_model=BotRegisterResponse)
def register_bot(
    request: BotRegisterRequest,
    use_case: Annotated[RegisterBotUseCase, Depends(get_register_bot_use_case)],
) -> BotRegisterResponse:
    """Register a Bot and return its settings (design-spec §11.1)."""
    _, settings = use_case.execute(
        device_id=request.device_id,
        firmware_version=request.firmware_version,
    )
    return BotRegisterResponse(bot_id=request.device_id, settings=settings_to_dict(settings))


@router.get("/{device_id}/commands", response_model=BotCommandsResponse)
def get_commands(
    device_id: str,
    publisher: Annotated[InMemoryBotEventPublisher, Depends(get_event_publisher)],
) -> BotCommandsResponse:
    """Return and clear queued control commands (design-spec §11.5)."""
    commands = publisher.drain(device_id)
    payload: list[dict[str, object]] = [{"type": c.type, **c.payload} for c in commands]
    return BotCommandsResponse(commands=payload)


@router.get("/{device_id}/wakeword", response_model=WakeWordResponse)
def get_wakeword(
    device_id: str,
    use_case: Annotated[ManageSettingsUseCase, Depends(get_settings_use_case)],
) -> WakeWordResponse:
    """Return the active wake word config (design-spec §11.6)."""
    settings = use_case.get_settings(device_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="device not found")
    config = settings.wake_word
    active = resolve_active_wake_words(config)
    return WakeWordResponse(
        enabled=config.enabled,
        wake_words=[
            WakeWordEntrySchema(
                id=w.id,
                phrase=w.phrase,
                model_name=w.model_name,
                threshold=w.threshold,
                enabled=w.enabled,
            )
            for w in active
        ],
    )
