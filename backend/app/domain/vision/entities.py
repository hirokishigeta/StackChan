"""Vision entities (design-spec §4.4 / §5 / §6)."""

from __future__ import annotations

from dataclasses import dataclass

from .value_objects import ProcessingLocation


@dataclass(frozen=True)
class VisionRecognitionConfig:
    """Vision recognition configuration."""

    provider: str = "dummy"
    model_name: str = "dummy-vision"
    face_tracking_enabled: bool = False
    motion_tracking_enabled: bool = False
    target_tracking_enabled: bool = False
    frame_interval_ms: int = 500
    resolution: str = "320x240"
    processing_location: ProcessingLocation = ProcessingLocation.BACKEND


@dataclass(frozen=True)
class VisionStreamPolicy:
    """Adaptive frame-send policy (design-spec §5.1)."""

    idle_fps: float = 1.0
    motion_detected_fps: float = 3.0
    face_detected_fps: float = 5.0
    tracking_fps: float = 8.0
    conversation_fps: float = 4.0
    resolution: str = "320x240"
    jpeg_quality: int = 70
    send_only_on_motion: bool = True
    max_frame_size: int = 65536
    processing_location: ProcessingLocation = ProcessingLocation.BACKEND


@dataclass(frozen=True)
class AttentionDetectionConfig:
    """Gaze / attention detection configuration (design-spec §6)."""

    enabled: bool = False
    require_face_centered: bool = True
    require_head_pose: bool = False
    require_gaze_estimation: bool = False
    attention_duration_ms: int = 1500
    confidence_threshold: float = 0.6


@dataclass(frozen=True)
class ProactiveTalkConfig:
    """Proactive talk configuration (design-spec §6.3 / §6.4)."""

    enabled: bool = False
    cooldown_seconds: int = 300
    max_count_per_day: int = 3
    allow_without_wake_word: bool = False
    allow_during_conversation: bool = False
    disabled_in_focus_mode: bool = True
    disabled_at_night: bool = True
