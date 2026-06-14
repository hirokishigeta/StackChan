"""Server-settings API (ADR-0009). GET / PUT the runtime-mutable voice config.

These settings are server-global (not per-device): the TTS voice persona the
backend synthesizes with. The effective value is the persisted dashboard
override layered onto the ``AppSettings`` / env defaults; the synthesizer reads
it per-call, so a change takes effect on the next utterance without a restart.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.application.use_cases.manage_server_settings import (
    ManageServerSettingsUseCase,
    UnknownVoiceSampleError,
)
from app.di_container.dependencies import get_server_settings_use_case
from app.domain.settings.value_objects import ServerVoiceSettings

router = APIRouter(prefix="/api/server-settings", tags=["server-settings"])

# Allowed TTS providers (must match the TTS registry; CLAUDE.md: no hard-coded
# magic strings outside their owning module — these mirror infrastructure/tts).
_ALLOWED_TTS_PROVIDERS = ("dummy", "irodori")


class ServerVoiceSettingsSchema(BaseModel):
    """HTTP representation of the server-global voice (TTS) settings."""

    tts_provider: str = Field(description="TTS provider id (dummy / irodori)")
    irodori_caption: str = Field(description="VoiceDesign caption (the voice prompt)")
    irodori_base_style: str = Field(description="Persona base style emoji prepended per utterance")
    voice_sample_id: str | None = Field(
        default=None,
        description="Selected pre-generated voice sample id (clones a fixed timbre); null = none",
    )

    @classmethod
    def from_domain(cls, voice: ServerVoiceSettings) -> ServerVoiceSettingsSchema:
        return cls(
            tts_provider=voice.tts_provider,
            irodori_caption=voice.irodori_caption,
            irodori_base_style=voice.irodori_base_style,
            voice_sample_id=voice.voice_sample_id,
        )


class ServerVoiceSettingsUpdate(BaseModel):
    """Request body for updating the server voice settings (all fields required)."""

    tts_provider: str = Field(description="TTS provider id (dummy / irodori)")
    irodori_caption: str
    irodori_base_style: str
    voice_sample_id: str | None = Field(
        default=None,
        description="Selected voice sample id (must exist); null = no sample selected",
    )


@router.get("")
def get_server_settings(
    use_case: Annotated[ManageServerSettingsUseCase, Depends(get_server_settings_use_case)],
) -> ServerVoiceSettingsSchema:
    """Return the effective server voice settings (override over env defaults)."""
    return ServerVoiceSettingsSchema.from_domain(use_case.current_voice())


@router.put("")
def update_server_settings(
    body: ServerVoiceSettingsUpdate,
    use_case: Annotated[ManageServerSettingsUseCase, Depends(get_server_settings_use_case)],
) -> ServerVoiceSettingsSchema:
    """Persist the server voice override and return the new effective value.

    An unknown ``tts_provider`` or an unknown ``voice_sample_id`` is rejected
    with HTTP 422. Caption / base_style are free text.
    """
    from fastapi import HTTPException

    if body.tts_provider not in _ALLOWED_TTS_PROVIDERS:
        allowed = ", ".join(_ALLOWED_TTS_PROVIDERS)
        raise HTTPException(
            status_code=422,
            detail=f"tts_provider: {body.tts_provider!r} (allowed: {allowed})",
        )
    try:
        updated = use_case.update_voice(
            ServerVoiceSettings(
                tts_provider=body.tts_provider,
                irodori_caption=body.irodori_caption,
                irodori_base_style=body.irodori_base_style,
                voice_sample_id=body.voice_sample_id,
            )
        )
    except UnknownVoiceSampleError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"voice_sample_id: {body.voice_sample_id!r} (unknown sample)",
        ) from exc
    return ServerVoiceSettingsSchema.from_domain(updated)
