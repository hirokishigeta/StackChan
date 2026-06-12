"""Vision domain services: attention detection (design-spec §6).

Pure, dependency-free logic used by the application layer. No FastAPI / OpenCV /
clock access lives here — the current time and the running attention duration
are passed in by the caller (testability, CLAUDE.md domain rule).

Initial implementation (design-spec §6.2): no head-pose / gaze estimation. A
face is treated as "looking at the Bot" when it is near the image centre, large
enough, confident enough, and has been so for ``attention_duration_ms``. The
``require_head_pose`` / ``require_gaze_estimation`` flags are accepted but not
yet evaluated — TODO(issue#6): add landmark / head-pose / gaze estimation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entities import AttentionDetectionConfig
from .value_objects import Detection, TrackingTarget


@dataclass(frozen=True)
class FrameGeometry:
    """The pixel dimensions of the analysed frame.

    Parsed from ``VisionRecognitionConfig.resolution`` (e.g. ``"320x240"``) so
    "centre" and "size" are evaluated relative to the actual frame.
    """

    width: int
    height: int

    @classmethod
    def from_resolution(cls, resolution: str) -> FrameGeometry:
        """Parse ``"WxH"``; fall back to 320x240 on a malformed value."""
        try:
            w_str, h_str = resolution.lower().split("x", 1)
            width = int(w_str)
            height = int(h_str)
        except (ValueError, AttributeError):
            return cls(width=320, height=240)
        if width <= 0 or height <= 0:
            return cls(width=320, height=240)
        return cls(width=width, height=height)


@dataclass(frozen=True)
class AttentionEvaluation:
    """Result of evaluating a single frame against the attention criteria."""

    # Spatial criteria met (centred ∧ large enough ∧ confident enough ∧ —
    # head-pose/gaze are TODO). Continuity is decided by the caller from the
    # accumulated duration.
    candidate: bool
    # The face that best satisfies the criteria (for look_at / tracking).
    target_detection: Detection | None
    # True when ``candidate`` held for at least ``attention_duration_ms``.
    attention_detected: bool


def select_primary_face(detections: tuple[Detection, ...]) -> Detection | None:
    """Pick the largest ``face`` detection (closest / most prominent person)."""
    faces = [d for d in detections if d.type == "face"]
    if not faces:
        return None
    return max(faces, key=lambda d: d.bbox.width * d.bbox.height)


def tracking_target_for(detection: Detection) -> TrackingTarget:
    """Centre point of a detection's bounding box (look_at target, §11.5)."""
    bbox = detection.bbox
    return TrackingTarget(x=bbox.x + bbox.width // 2, y=bbox.y + bbox.height // 2)


def evaluate_attention(
    *,
    detections: tuple[Detection, ...],
    config: AttentionDetectionConfig,
    geometry: FrameGeometry,
    accumulated_duration_ms: int,
) -> AttentionEvaluation:
    """Evaluate whether a frame meets the attention criteria (design-spec §6.2).

    ``accumulated_duration_ms`` is how long the candidate condition has held so
    far (tracked by the caller across frames). The continuity threshold is
    ``config.attention_duration_ms``.
    """
    face = select_primary_face(detections)
    if face is None:
        return AttentionEvaluation(candidate=False, target_detection=None, attention_detected=False)

    if face.confidence < config.confidence_threshold:
        return AttentionEvaluation(candidate=False, target_detection=face, attention_detected=False)

    if config.require_face_centered and not _is_centered(face, geometry):
        return AttentionEvaluation(candidate=False, target_detection=face, attention_detected=False)

    if not _is_large_enough(face, geometry):
        return AttentionEvaluation(candidate=False, target_detection=face, attention_detected=False)

    # TODO(issue#6): evaluate config.require_head_pose / require_gaze_estimation
    # once landmark / head-pose / gaze estimation is available (design-spec §6.2
    # developed implementation). For now these flags do not gate the candidate.

    detected = accumulated_duration_ms >= config.attention_duration_ms
    return AttentionEvaluation(candidate=True, target_detection=face, attention_detected=detected)


# A face counts as "centred" when its centre lies within this fraction of the
# frame's half-extent from the middle (design-spec §6.2 "画面中央付近").
_CENTER_TOLERANCE = 0.30
# Minimum face width relative to the frame width ("顔サイズ一定以上", §6.2).
_MIN_FACE_WIDTH_RATIO = 0.15


def _is_centered(face: Detection, geometry: FrameGeometry) -> bool:
    cx = face.bbox.x + face.bbox.width / 2
    cy = face.bbox.y + face.bbox.height / 2
    dx = abs(cx - geometry.width / 2) / (geometry.width / 2)
    dy = abs(cy - geometry.height / 2) / (geometry.height / 2)
    return dx <= _CENTER_TOLERANCE and dy <= _CENTER_TOLERANCE


def _is_large_enough(face: Detection, geometry: FrameGeometry) -> bool:
    return face.bbox.width >= geometry.width * _MIN_FACE_WIDTH_RATIO
