"""Voice-samples API (ADR-0012).

Lists the pre-generated reference voices and serves each wav for in-browser
preview so the dashboard can let the user pick a timbre. The selection itself is
persisted via ``/api/server-settings`` (``voice_sample_id``).

``GET  /api/voice-samples``            -> [{id, label}]
``GET  /api/voice-samples/{id}/audio`` -> the wav (audio/wav), 404 if unknown.
``POST /api/voice-samples``            -> mint a reference voice (ADR-0013).

Path traversal is blocked in the repository (a resolved wav must live inside the
samples dir); an id that escapes resolves to ``None`` and yields 404 here.

``POST`` generates a clean reference voice on the GPU from a caption + example
text and saves it as a new selectable sample. Error mapping: invalid slug /
empty caption -> 422, duplicate id -> 409, synthesis unavailable -> 503.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.application.ports.speech_synthesizer import SpeechSynthesisError
from app.application.ports.voice_sample_repository import (
    DuplicateSampleError,
    InvalidSampleIdError,
    VoiceSampleRepository,
)
from app.application.use_cases.generate_voice_sample import GenerateVoiceSampleUseCase
from app.di_container.dependencies import (
    get_generate_voice_sample_use_case,
    get_voice_sample_repository,
)
from app.domain.speech.value_objects import VoiceSample

# The project's canonical example sentence, used as the default generation text.
_DEFAULT_EXAMPLE_TEXT = "こんにちは、今日はどんなお話をしましょうか？"

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


class GenerateVoiceSampleBody(BaseModel):
    """Request to mint a new reference voice (ADR-0013)."""

    id: str = Field(description="New sample id (a safe slug: letters/digits/-/_)")
    label: str | None = Field(default=None, description="Human-friendly label (defaults to the id)")
    caption: str = Field(
        min_length=1,
        description="VoiceDesign caption describing the target voice (required)",
    )
    text: str = Field(
        default=_DEFAULT_EXAMPLE_TEXT,
        description="Example sentence to synthesize for the reference",
    )


@router.post("", status_code=201)
def create_voice_sample(
    body: GenerateVoiceSampleBody,
    use_case: Annotated[GenerateVoiceSampleUseCase, Depends(get_generate_voice_sample_use_case)],
) -> VoiceSampleSchema:
    """Generate + persist a reference voice, returning the new {id, label}.

    Caption must be non-empty (422 via the schema). An empty/whitespace caption
    or text is treated as invalid (422). Bad slug -> 422, duplicate id -> 409,
    and an unavailable / failed synthesizer -> 503 (generation runs on the GPU
    host; this backend may not have the engine).
    """
    if not body.caption.strip() or not body.text.strip():
        raise HTTPException(status_code=422, detail="caption and text must be non-empty")
    try:
        sample = use_case.execute(
            sample_id=body.id,
            caption=body.caption.strip(),
            text=body.text.strip(),
            label=body.label,
        )
    except InvalidSampleIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateSampleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SpeechSynthesisError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"voice generation is unavailable: {exc}",
        ) from exc
    return VoiceSampleSchema.from_domain(sample)


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
