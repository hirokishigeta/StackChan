"""Vision routes: detection (§11.4) + attention / proactive talk (§6).

``/detect`` returns raw detections (§11.4). ``/attention`` additionally
evaluates whether the user is looking at the Bot and, when the §6.3/§6.4 guards
pass, queues a proactive-talk command set for the device to poll (§11.5).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.application.use_cases.detect_attention import DetectAttentionUseCase
from app.application.use_cases.run_vision_detection import RunVisionDetectionUseCase
from app.di_container.dependencies import get_attention_use_case, get_vision_use_case

from .schemas import (
    BBoxSchema,
    DetectionSchema,
    TrackingTargetSchema,
    VisionAttentionResponse,
    VisionDetectResponse,
)

router = APIRouter(prefix="/api/vision", tags=["vision"])


def _detection_schemas(detections: object) -> list[DetectionSchema]:
    # ``detections`` is a tuple[Detection, ...]; typed loosely to avoid importing
    # the domain VO here (kept thin per CLAUDE.md interfaces rule).
    items: list[DetectionSchema] = []
    for d in detections:  # type: ignore[attr-defined]
        items.append(
            DetectionSchema(
                type=d.type,
                bbox=BBoxSchema(x=d.bbox.x, y=d.bbox.y, width=d.bbox.width, height=d.bbox.height),
                confidence=d.confidence,
            )
        )
    return items


def _target_schema(target: object) -> TrackingTargetSchema | None:
    if target is None:
        return None
    return TrackingTargetSchema(x=target.x, y=target.y)  # type: ignore[attr-defined]


@router.post("/detect", response_model=VisionDetectResponse)
async def detect(
    request: Request,
    use_case: Annotated[RunVisionDetectionUseCase, Depends(get_vision_use_case)],
    device_id: str | None = None,
) -> VisionDetectResponse:
    """Run detection on a raw image body (image/jpeg | image/raw) — §11.4."""
    image = await request.body()
    result = await use_case.execute(image=image, device_id=device_id)
    return VisionDetectResponse(
        detections=_detection_schemas(result.detections),
        tracking_target=_target_schema(result.tracking_target),
    )


@router.post("/attention", response_model=VisionAttentionResponse)
async def attention(
    request: Request,
    use_case: Annotated[DetectAttentionUseCase, Depends(get_attention_use_case)],
    device_id: str,
    conversation_active: bool = False,
) -> VisionAttentionResponse:
    """Evaluate attention and (if allowed) queue a proactive talk — §6."""
    image = await request.body()
    result = await use_case.execute(
        image=image,
        device_id=device_id,
        conversation_active=conversation_active,
    )
    decision = result.proactive_decision.value if result.proactive_decision is not None else None
    return VisionAttentionResponse(
        detections=_detection_schemas(result.detection.detections),
        tracking_target=_target_schema(result.detection.tracking_target),
        state=result.state.value,
        attention_detected=result.attention_detected,
        proactive_decision=decision,
        proactive_text=result.proactive_text,
    )
