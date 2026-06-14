"""Serialization helpers between domain dataclasses and persisted JSON.

The domain models are frozen dataclasses with no external dependencies
(CLAUDE.md). This module converts them to/from plain dicts so the SQLite
repository can store the settings aggregate as JSON without leaking
persistence concerns into the domain.
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Any, TypeVar

from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentType, ResponseMode
from app.domain.settings.entities import BotSettings
from app.domain.settings.value_objects import DisplaySettings
from app.domain.speech.entities import ConversationTurnConfig, SpeechRecognitionConfig
from app.domain.vision.entities import (
    AttentionDetectionConfig,
    ProactiveTalkConfig,
    VisionRecognitionConfig,
    VisionStreamPolicy,
)
from app.domain.vision.value_objects import ProcessingLocation
from app.domain.wakeword.entities import EndWordConfig, WakeWordConfig
from app.domain.wakeword.value_objects import EndWordEntry, WakeWordEntry


def _to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses / enums / tuples to JSON-safe values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


_logger = logging.getLogger(__name__)

_E = TypeVar("_E", bound=Enum)

# Single source of truth for every enum-valued field in the persisted settings
# aggregate, keyed by (section, field) where ``section`` is a top-level key in
# the settings dict. Both the lenient load path (``_coerce_enum``) and the
# strict input validator (``validate_enum_inputs``) consume this so the enum
# knowledge is declared in exactly one place (no per-field if-branches).
_ENUM_FIELDS: tuple[tuple[str, str, type[Enum]], ...] = (
    ("agent", "agent_type", AgentType),
    ("agent", "response_mode", ResponseMode),
    ("vision", "processing_location", ProcessingLocation),
    ("vision_stream", "processing_location", ProcessingLocation),
)


def _coerce_enum(enum_cls: type[_E], raw: Any, default: _E) -> _E:
    """Parse ``raw`` into ``enum_cls``, falling back to ``default`` if unknown.

    Used by the load/deserialize path: per design-spec §13 (stability),
    settings that fail to load must not crash startup or reads, so an unknown
    persisted enum value silently degrades to the field default (and is logged).
    """
    try:
        return enum_cls(raw)
    except ValueError:
        _logger.warning(
            "Unknown %s value %r in persisted settings; falling back to default %r",
            enum_cls.__name__,
            raw,
            default.value,
        )
        return default


def validate_enum_inputs(data: dict[str, Any]) -> None:
    """Reject unknown enum values in user-supplied settings input.

    Raises ``ValueError`` (mapped to HTTP 422 by the route) when any enum field
    carries a value the corresponding enum cannot parse. Unlike the load path,
    user input is validated strictly so configuration mistakes are not silently
    swallowed into defaults.
    """
    invalid: list[str] = []
    for section, field, enum_cls in _ENUM_FIELDS:
        section_data = data.get(section)
        if not isinstance(section_data, dict) or field not in section_data:
            continue
        raw = section_data[field]
        try:
            enum_cls(raw)
        except ValueError:
            allowed = ", ".join(member.value for member in enum_cls)
            invalid.append(f"{section}.{field}: {raw!r} (allowed: {allowed})")
    if invalid:
        raise ValueError("invalid settings value(s): " + "; ".join(invalid))


def settings_to_dict(settings: BotSettings) -> dict[str, Any]:
    """Serialize a ``BotSettings`` aggregate to a JSON-safe dict."""
    return _to_jsonable(settings)  # type: ignore[no-any-return]


def settings_from_dict(device_id: str, data: dict[str, Any]) -> BotSettings:
    """Rebuild a ``BotSettings`` aggregate from a persisted dict.

    Missing keys fall back to defaults, so older persisted rows remain
    readable as the schema grows.
    """
    defaults = BotSettings.default(device_id)

    agent_raw = data.get("agent", {})
    agent = AgentProfile(
        agent_type=_coerce_enum(
            AgentType,
            agent_raw.get("agent_type", defaults.agent.agent_type.value),
            defaults.agent.agent_type,
        ),
        model_name=agent_raw.get("model_name", defaults.agent.model_name),
        system_prompt=agent_raw.get("system_prompt", defaults.agent.system_prompt),
        tools_enabled=agent_raw.get("tools_enabled", defaults.agent.tools_enabled),
        memory_enabled=agent_raw.get("memory_enabled", defaults.agent.memory_enabled),
        temperature=agent_raw.get("temperature", defaults.agent.temperature),
        max_tokens=agent_raw.get("max_tokens", defaults.agent.max_tokens),
        response_mode=_coerce_enum(
            ResponseMode,
            agent_raw.get("response_mode", defaults.agent.response_mode.value),
            defaults.agent.response_mode,
        ),
    )

    speech_raw = data.get("speech", {})
    speech = SpeechRecognitionConfig(
        provider=speech_raw.get("provider", defaults.speech.provider),
        model_name=speech_raw.get("model_name", defaults.speech.model_name),
        language=speech_raw.get("language", defaults.speech.language),
        vad_enabled=speech_raw.get("vad_enabled", defaults.speech.vad_enabled),
        noise_reduction_enabled=speech_raw.get(
            "noise_reduction_enabled", defaults.speech.noise_reduction_enabled
        ),
        streaming_enabled=speech_raw.get("streaming_enabled", defaults.speech.streaming_enabled),
    )

    turn_raw = data.get("conversation_turn", {})
    conversation_turn = _build_conversation_turn(turn_raw, defaults.conversation_turn)

    vision_raw = data.get("vision", {})
    vision = VisionRecognitionConfig(
        provider=vision_raw.get("provider", defaults.vision.provider),
        model_name=vision_raw.get("model_name", defaults.vision.model_name),
        face_tracking_enabled=vision_raw.get(
            "face_tracking_enabled", defaults.vision.face_tracking_enabled
        ),
        motion_tracking_enabled=vision_raw.get(
            "motion_tracking_enabled", defaults.vision.motion_tracking_enabled
        ),
        target_tracking_enabled=vision_raw.get(
            "target_tracking_enabled", defaults.vision.target_tracking_enabled
        ),
        frame_interval_ms=vision_raw.get("frame_interval_ms", defaults.vision.frame_interval_ms),
        resolution=vision_raw.get("resolution", defaults.vision.resolution),
        processing_location=_coerce_enum(
            ProcessingLocation,
            vision_raw.get("processing_location", defaults.vision.processing_location.value),
            defaults.vision.processing_location,
        ),
    )

    wake_raw = data.get("wake_word", {})
    # ``detection_method`` / ``max_local_active`` were removed (ADR-0017); ignore
    # them if present in older persisted rows (back-compat) rather than erroring.
    wake_word = WakeWordConfig(
        enabled=wake_raw.get("enabled", defaults.wake_word.enabled),
        wake_words=tuple(
            WakeWordEntry(
                id=w["id"],
                phrase=w["phrase"],
                model_name=w.get("model_name", "default"),
                threshold=w.get("threshold", 0.7),
                enabled=w.get("enabled", True),
            )
            for w in wake_raw.get("wake_words", [])
        ),
    )

    # End words (ADR-0016). When the key is absent (older persisted rows that
    # predate the field), fall back to the default per-device list so existing
    # devices keep ending conversations on the same JP phrases. When the key is
    # present, it is authoritative (an explicit empty list means "no end words"
    # -> the WS gate falls back to the global AppSettings list at runtime).
    end_word = _build_end_word(data.get("end_word"), defaults.end_word)

    display_raw = data.get("display", {})
    display = DisplaySettings(
        brightness=display_raw.get("brightness", defaults.display.brightness),
        theme=display_raw.get("theme", defaults.display.theme),
        volume=display_raw.get("volume", defaults.display.volume),
    )

    return BotSettings(
        device_id=device_id,
        agent=agent,
        speech=speech,
        conversation_turn=conversation_turn,
        vision=vision,
        vision_stream=_build_vision_stream(data.get("vision_stream", {}), defaults.vision_stream),
        attention=_build_attention(data.get("attention", {}), defaults.attention),
        proactive_talk=_build_proactive(data.get("proactive_talk", {}), defaults.proactive_talk),
        wake_word=wake_word,
        end_word=end_word,
        display=display,
    )


def _build_end_word(raw: Any, default: EndWordConfig) -> EndWordConfig:
    """Rebuild ``EndWordConfig`` from persisted JSON (ADR-0016).

    ``raw is None`` means the key was absent (back-compat) -> keep the default
    per-device list. A present dict (even with an empty ``end_words`` list) is
    authoritative.
    """
    if raw is None:
        return default
    return EndWordConfig(
        end_words=tuple(
            EndWordEntry(
                id=w["id"],
                phrase=w["phrase"],
                enabled=w.get("enabled", True),
            )
            for w in raw.get("end_words", [])
        ),
    )


def _build_conversation_turn(
    raw: dict[str, Any], default: ConversationTurnConfig
) -> ConversationTurnConfig:
    return ConversationTurnConfig(
        barge_in_enabled=raw.get("barge_in_enabled", default.barge_in_enabled),
        aec_enabled=raw.get("aec_enabled", default.aec_enabled),
        vad_threshold=raw.get("vad_threshold", default.vad_threshold),
        vad_threshold_while_speaking=raw.get(
            "vad_threshold_while_speaking", default.vad_threshold_while_speaking
        ),
        min_interruption_duration_ms=raw.get(
            "min_interruption_duration_ms", default.min_interruption_duration_ms
        ),
        end_of_turn_silence_ms=raw.get("end_of_turn_silence_ms", default.end_of_turn_silence_ms),
        semantic_end_of_turn_enabled=raw.get(
            "semantic_end_of_turn_enabled", default.semantic_end_of_turn_enabled
        ),
        max_utterance_duration_ms=raw.get(
            "max_utterance_duration_ms", default.max_utterance_duration_ms
        ),
        interrupt_behavior=raw.get("interrupt_behavior", default.interrupt_behavior),
    )


def _build_vision_stream(raw: dict[str, Any], default: VisionStreamPolicy) -> VisionStreamPolicy:
    return VisionStreamPolicy(
        idle_fps=raw.get("idle_fps", default.idle_fps),
        motion_detected_fps=raw.get("motion_detected_fps", default.motion_detected_fps),
        face_detected_fps=raw.get("face_detected_fps", default.face_detected_fps),
        tracking_fps=raw.get("tracking_fps", default.tracking_fps),
        conversation_fps=raw.get("conversation_fps", default.conversation_fps),
        resolution=raw.get("resolution", default.resolution),
        jpeg_quality=raw.get("jpeg_quality", default.jpeg_quality),
        send_only_on_motion=raw.get("send_only_on_motion", default.send_only_on_motion),
        max_frame_size=raw.get("max_frame_size", default.max_frame_size),
        processing_location=_coerce_enum(
            ProcessingLocation,
            raw.get("processing_location", default.processing_location.value),
            default.processing_location,
        ),
    )


def _build_attention(
    raw: dict[str, Any], default: AttentionDetectionConfig
) -> AttentionDetectionConfig:
    return AttentionDetectionConfig(
        enabled=raw.get("enabled", default.enabled),
        require_face_centered=raw.get("require_face_centered", default.require_face_centered),
        require_head_pose=raw.get("require_head_pose", default.require_head_pose),
        require_gaze_estimation=raw.get("require_gaze_estimation", default.require_gaze_estimation),
        attention_duration_ms=raw.get("attention_duration_ms", default.attention_duration_ms),
        confidence_threshold=raw.get("confidence_threshold", default.confidence_threshold),
    )


def _build_proactive(raw: dict[str, Any], default: ProactiveTalkConfig) -> ProactiveTalkConfig:
    return ProactiveTalkConfig(
        enabled=raw.get("enabled", default.enabled),
        cooldown_seconds=raw.get("cooldown_seconds", default.cooldown_seconds),
        max_count_per_day=raw.get("max_count_per_day", default.max_count_per_day),
        allow_without_wake_word=raw.get("allow_without_wake_word", default.allow_without_wake_word),
        allow_during_conversation=raw.get(
            "allow_during_conversation", default.allow_during_conversation
        ),
        disabled_in_focus_mode=raw.get("disabled_in_focus_mode", default.disabled_in_focus_mode),
        disabled_at_night=raw.get("disabled_at_night", default.disabled_at_night),
    )
