"""Speech recognition route (design-spec §11.2). Dummy ASR in this phase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.application.use_cases.process_voice_input import ProcessVoiceInputUseCase
from app.di_container.dependencies import get_voice_use_case

from .schemas import SpeechRecognizeResponse

router = APIRouter(prefix="/api/speech", tags=["speech"])


@router.post("/recognize", response_model=SpeechRecognizeResponse)
async def recognize(
    request: Request,
    use_case: Annotated[ProcessVoiceInputUseCase, Depends(get_voice_use_case)],
    device_id: str | None = None,
) -> SpeechRecognizeResponse:
    """Transcribe raw audio body (audio/wav | audio/pcm) — design-spec §11.2."""
    audio = await request.body()
    result = await use_case.execute(audio=audio, device_id=device_id)
    return SpeechRecognizeResponse(
        text=result.text,
        language=result.language,
        confidence=result.confidence,
    )
