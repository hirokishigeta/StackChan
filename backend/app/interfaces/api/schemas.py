"""Pydantic request/response schemas for the Bot-facing API (design-spec §11)."""

from __future__ import annotations

from pydantic import BaseModel, Field

# --- Bot register (§11.1) -------------------------------------------------


class CapabilitiesSchema(BaseModel):
    microphone: bool = True
    speaker: bool = True
    camera: bool = True
    display: bool = True
    touch: bool = True
    wake_word: bool = True


class BotRegisterRequest(BaseModel):
    device_id: str
    firmware_version: str
    capabilities: CapabilitiesSchema = Field(default_factory=CapabilitiesSchema)


class BotRegisterResponse(BaseModel):
    bot_id: str
    settings: dict[str, object]


# --- Speech recognition (§11.2) ------------------------------------------


class SpeechRecognizeResponse(BaseModel):
    text: str
    language: str
    confidence: float


# --- Agent chat (§11.3) --------------------------------------------------


class AgentChatRequest(BaseModel):
    device_id: str
    message: str
    context: dict[str, object] = Field(default_factory=dict)


class AgentActionSchema(BaseModel):
    type: str
    value: str | None = None


class AgentChatResponse(BaseModel):
    text: str
    emotion: str
    actions: list[AgentActionSchema]


# --- Proactive talk Agent request (§11.7) --------------------------------


class AgentProactiveRequest(BaseModel):
    device_id: str
    event_type: str = "attention_detected"
    context: dict[str, object] = Field(default_factory=dict)


# --- Vision detect (§11.4) -----------------------------------------------


class BBoxSchema(BaseModel):
    x: int
    y: int
    width: int
    height: int


class DetectionSchema(BaseModel):
    type: str
    bbox: BBoxSchema
    confidence: float


class TrackingTargetSchema(BaseModel):
    x: int
    y: int


class VisionDetectResponse(BaseModel):
    detections: list[DetectionSchema]
    tracking_target: TrackingTargetSchema | None = None


# --- Attention detection + proactive talk (design-spec §6) ----------------


class VisionAttentionResponse(BaseModel):
    """Result of evaluating a frame for attention / proactive talk (§6).

    Commands (look_at / set_expression / proactive_speak) are queued for the
    device to poll via ``GET /api/bot/{device_id}/commands`` (§11.5); this body
    reports the evaluation outcome for observability / the dashboard.
    """

    detections: list[DetectionSchema]
    tracking_target: TrackingTargetSchema | None = None
    state: str
    attention_detected: bool
    # One of ProactiveDecision (allowed / cooldown / max_per_day / ...), or null
    # when attention was not detected this frame.
    proactive_decision: str | None = None
    proactive_text: str | None = None


# --- Bot commands (§11.5) ------------------------------------------------


class CommandSchema(BaseModel):
    type: str
    # Remaining command-specific fields are flattened in here.
    payload: dict[str, object] = Field(default_factory=dict)


class BotCommandsResponse(BaseModel):
    commands: list[dict[str, object]]


# --- Wake word (§11.6) ----------------------------------------------------


class WakeWordEntrySchema(BaseModel):
    id: str
    phrase: str
    model_name: str = "default"
    threshold: float = 0.7
    enabled: bool = True


class WakeWordResponse(BaseModel):
    enabled: bool
    wake_words: list[WakeWordEntrySchema]
