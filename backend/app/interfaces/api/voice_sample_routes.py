"""Voice-samples API (ADR-0012).

Lists the pre-generated reference voices and serves each wav for in-browser
preview so the dashboard can let the user pick a timbre. The selection itself is
persisted via ``/api/server-settings`` (``voice_sample_id``).

``GET  /api/voice-samples``            -> [{id, label}]
``GET  /api/voice-samples/{id}/audio`` -> the wav (audio/wav), 404 if unknown.

Path traversal is blocked in the repository (a resolved wav must live inside the
samples dir); an id that escapes resolves to ``None`` and yields 404 here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.di_container.dependencies import get_voice_sample_repository
from app.domain.speech.value_objects import VoiceSample

router = APIRouter(prefix="/api/voice-samples", tags=["voice-samples"])


class VoiceSampleSchema(BaseModel):
    """HTTP representation of one selectable reference voice."""

    id: str = Field(description="Sample id (the wav filename stem)")
    label: str = Field(description="Human-friendly label (defaults to the id)")

    @classmethod
    def from_domain(cls, sample: VoiceSample) -> VoiceSampleSchema:
        return cls(id=sample.id, label=sample.label)


@router.get("")
def list_voice_samples(
    repository: Annotated[VoiceSampleRepository, Depends(get_voice_sample_repository)],
) -> list[VoiceSampleSchema]:
    """Return all available voice samples (empty if the dir is missing/empty)."""
    return [VoiceSampleSchema.from_domain(s) for s in repository.list_samples()]


@router.get("/{sample_id}/audio")
def get_voice_sample_audio(
    sample_id: str,
    repository: Annotated[VoiceSampleRepository, Depends(get_voice_sample_repository)],
) -> FileResponse:
    """Stream the sample's wav for in-browser preview; 404 on unknown id.

    Unknown / traversal-bearing ids resolve to ``None`` in the repository.
    """
    wav_path = repository.resolve_wav_path(sample_id)
    if wav_path is None:
        raise HTTPException(status_code=404, detail=f"voice sample not found: {sample_id!r}")
    return FileResponse(wav_path, media_type="audio/wav", filename=f"{sample_id}.wav")
