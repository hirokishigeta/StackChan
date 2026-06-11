"""Vision value objects (design-spec §4.4 / §5 / §6 / §11.4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProcessingLocation(StrEnum):
    """Where a recognition workload runs."""

    DEVICE = "device"
    BACKEND = "backend"


class VisionState(StrEnum):
    """Vision-driven Bot state (design-spec §5 / §6.5)."""

    IDLE = "Idle"
    MOTION_DETECTED = "MotionDetected"
    FACE_DETECTED = "FaceDetected"
    TRACKING = "Tracking"
    ATTENTION_DETECTED = "AttentionDetected"
    CONVERSATION = "Conversation"


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in image pixel coordinates."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Detection:
    """A single detected object (e.g. a face)."""

    type: str
    bbox: BoundingBox
    confidence: float


@dataclass(frozen=True)
class TrackingTarget:
    """A point the Bot should look toward."""

    x: int
    y: int


@dataclass(frozen=True)
class VisionDetectionResult:
    """Result of running detection on a frame (design-spec §11.4)."""

    detections: tuple[Detection, ...] = ()
    tracking_target: TrackingTarget | None = None
