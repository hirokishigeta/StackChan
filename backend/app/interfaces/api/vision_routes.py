"""Vision detection route (design-spec §11.4). Dummy detector in this phase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.application.use_cases.run_vision_detection import RunVisionDetectionUseCase
from app.di_container.dependencies import get_vision_use_case

from .schemas import BBoxSchema, DetectionSchema, TrackingTargetSchema, VisionDetectResponse

router = APIRouter(prefix="/api/vision", tags=["vision"])


@router.post("/detect", response_model=VisionDetectResponse)
async def detect(
    request: Request,
    use_case: Annotated[RunVisionDetectionUseCase, Depends(get_vision_use_case)],
    device_id: str | None = None,
) -> VisionDetectResponse:
    """Run detection on a raw image body (image/jpeg | image/raw) — §11.4."""
    image = await request.body()
    result = await use_case.execute(image=image, device_id=device_id)
    target = None
    if result.tracking_target is not None:
        target = TrackingTargetSchema(x=result.tracking_target.x, y=result.tracking_target.y)
    return VisionDetectResponse(
        detections=[
            DetectionSchema(
                type=d.type,
                bbox=BBoxSchema(x=d.bbox.x, y=d.bbox.y, width=d.bbox.width, height=d.bbox.height),
                confidence=d.confidence,
            )
            for d in result.detections
        ],
        tracking_target=target,
    )
