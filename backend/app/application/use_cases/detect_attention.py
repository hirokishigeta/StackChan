"""Use case: attention detection + proactive talk (design-spec §6).

Consumes a single camera frame (sent by the device at an adaptive rate, §5 —
device side is TODO(issue#5)), runs face detection, evaluates whether the user
is looking at the Bot, and — if all the §6.3/§6.4 guards pass — asks the
AgentGateway for a proactive utterance and queues the resulting commands
(``proactive_speak`` + ``set_expression`` + ``look_at``) for the device to poll
via ``GET /api/bot/{device_id}/commands`` (§11.5).

The clock is injected (``now_provider``) so cooldown / daily-cap / continuity are
deterministic in tests. Per-device runtime state (VisionState, attention
continuity, proactive history) lives in an in-memory session store for this
phase — TODO(issue#8): move to a durable / shared store if multi-process.

Stability (design-spec §13): detection or agent failures never raise out of
:meth:`execute`; they degrade to "no proactive talk" so the device loop / camera
path is not broken by one bad frame.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.ports.agent_gateway import AgentError, AgentGateway
from app.application.ports.bot_event_publisher import BotEventPublisher
from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.vision_recognizer import VisionRecognizer
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent
from app.domain.bot.value_objects import BotCommand
from app.domain.settings.entities import BotSettings
from app.domain.vision.entities import AttentionDetectionConfig, ProactiveTalkConfig
from app.domain.vision.proactive import (
    ProactiveDecision,
    VisionSession,
    evaluate_proactive_talk,
    next_state,
)
from app.domain.vision.services import (
    FrameGeometry,
    evaluate_attention,
    select_primary_face,
    tracking_target_for,
)
from app.domain.vision.value_objects import (
    Detection,
    TrackingTarget,
    VisionDetectionResult,
    VisionState,
)

_logger = logging.getLogger(__name__)

NowProvider = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AttentionResult:
    """Outcome of one frame's attention evaluation (also the HTTP response)."""

    detection: VisionDetectionResult
    state: VisionState
    attention_detected: bool
    proactive_decision: ProactiveDecision | None
    proactive_text: str | None


class SessionStore:
    """In-memory per-device :class:`VisionSession` store (this phase)."""

    def __init__(self) -> None:
        self._sessions: dict[str, VisionSession] = {}

    def get(self, device_id: str) -> VisionSession:
        session = self._sessions.get(device_id)
        if session is None:
            session = VisionSession()
            self._sessions[device_id] = session
        return session


class DetectAttentionUseCase:
    """Detect attention from a frame and trigger a guarded proactive talk."""

    def __init__(
        self,
        recognizer: VisionRecognizer,
        repository: SettingsRepository,
        gateway: AgentGateway,
        publisher: BotEventPublisher,
        *,
        sessions: SessionStore,
        now_provider: NowProvider = _utc_now,
    ) -> None:
        self._recognizer = recognizer
        self._repository = repository
        self._gateway = gateway
        self._publisher = publisher
        self._sessions = sessions
        self._now = now_provider

    async def execute(
        self,
        *,
        image: bytes,
        device_id: str,
        conversation_active: bool = False,
    ) -> AttentionResult:
        """Process one frame for ``device_id`` (design-spec §6)."""
        now = self._now()
        settings = self._resolve_settings(device_id)
        detection = await self._detect(image=image, settings=settings)

        session = self._sessions.get(device_id)
        evaluation = self._evaluate(
            detection, settings.attention, settings.vision.resolution, session, now
        )

        # A face being present (FaceDetected) is distinct from it meeting the
        # attention criteria (centred/large/confident → candidate).
        face_present = select_primary_face(detection.detections) is not None
        attention_detected = evaluation.attention_detected
        session.state = next_state(
            current=session.state,
            face_present=face_present,
            attention_detected=attention_detected,
            conversation_active=conversation_active,
        )

        decision: ProactiveDecision | None = None
        proactive_text: str | None = None
        if attention_detected:
            decision, proactive_text = await self._maybe_talk(
                device_id=device_id,
                settings=settings,
                session=session,
                detection=detection,
                evaluation_target=evaluation.target_detection,
                conversation_active=conversation_active,
                now=now,
            )

        return AttentionResult(
            detection=detection,
            state=session.state,
            attention_detected=attention_detected,
            proactive_decision=decision,
            proactive_text=proactive_text,
        )

    # -- internals --------------------------------------------------------

    def _resolve_settings(self, device_id: str) -> BotSettings:
        settings = self._repository.get_settings(device_id)
        return settings if settings is not None else BotSettings.default(device_id)

    async def _detect(self, *, image: bytes, settings: BotSettings) -> VisionDetectionResult:
        try:
            return await self._recognizer.detect(image=image, config=settings.vision)
        except Exception:  # noqa: BLE001 - one bad frame must not break the loop (§13)
            _logger.warning("vision detect failed; treating as no detection", exc_info=True)
            return VisionDetectionResult()

    def _evaluate(
        self,
        detection: VisionDetectionResult,
        config: AttentionDetectionConfig,
        resolution: str,
        session: VisionSession,
        now: datetime,
    ) -> _Evaluation:
        geometry = FrameGeometry.from_resolution(resolution)
        # First pass with the duration accumulated *before* this frame, so a
        # newly-appearing centred face does not instantly satisfy continuity.
        prior_ms = session.candidate_duration_ms(now)
        result = evaluate_attention(
            detections=detection.detections,
            config=config,
            geometry=geometry,
            accumulated_duration_ms=prior_ms,
        )
        if result.candidate:
            if session.candidate_since is None:
                session.candidate_since = now
        else:
            session.candidate_since = None
        return _Evaluation(
            attention_detected=result.attention_detected,
            target_detection=result.target_detection if result.candidate else None,
        )

    async def _maybe_talk(
        self,
        *,
        device_id: str,
        settings: BotSettings,
        session: VisionSession,
        detection: VisionDetectionResult,
        evaluation_target: Detection | None,
        conversation_active: bool,
        now: datetime,
    ) -> tuple[ProactiveDecision, str | None]:
        config: ProactiveTalkConfig = settings.proactive_talk
        decision = evaluate_proactive_talk(
            config=config,
            history=session.history,
            now=now,
            conversation_active=conversation_active,
        )
        if decision is not ProactiveDecision.ALLOWED:
            return decision, None

        reply = await self._proactive_reply(device_id, settings.agent, session, now)
        if reply is None:
            # Agent failed: do not record cooldown so a later frame can retry.
            return ProactiveDecision.ALLOWED, None

        # Record now (consumes cooldown / daily cap) and queue commands.
        session.history = session.history.record(now)
        target = self._look_at_target(detection, evaluation_target)
        await self._queue_commands(device_id=device_id, reply=reply, target=target)
        return ProactiveDecision.ALLOWED, reply.text

    async def _proactive_reply(
        self,
        device_id: str,
        profile: AgentProfile,
        session: VisionSession,
        now: datetime,
    ) -> AgentReply | None:
        last_seconds = session.history.seconds_since_last(now)
        event = ProactiveEvent.from_context(
            event_type="attention_detected",
            context={
                "face_detected": True,
                "conversation_active": False,
                "last_proactive_talk_seconds_ago": (
                    int(last_seconds) if last_seconds is not None else None
                ),
            },
        )
        try:
            return await self._gateway.proactive(event=event, profile=profile)
        except AgentError:
            _logger.warning("proactive agent call failed for %s; skipping turn", device_id)
            return None

    @staticmethod
    def _look_at_target(
        detection: VisionDetectionResult, evaluation_target: Detection | None
    ) -> TrackingTarget | None:
        if detection.tracking_target is not None:
            return detection.tracking_target
        if evaluation_target is not None:
            return tracking_target_for(evaluation_target)
        return None

    async def _queue_commands(
        self,
        *,
        device_id: str,
        reply: AgentReply,
        target: TrackingTarget | None,
    ) -> None:
        commands: list[BotCommand] = []
        if target is not None:
            commands.append(
                BotCommand(
                    type="look_at",
                    payload={"target": {"x": target.x, "y": target.y}, "confidence": 0.86},
                )
            )
        # set_expression from the agent's emotion (fallback to the emotion field).
        expression = self._expression_from(reply)
        if expression is not None:
            commands.append(BotCommand(type="set_expression", payload={"value": expression}))
        commands.append(
            BotCommand(
                type="proactive_speak",
                payload={"reason": "attention_detected", "text": reply.text},
            )
        )
        for command in commands:
            await self._publisher.publish_command(device_id=device_id, command=command)

    @staticmethod
    def _expression_from(reply: AgentReply) -> str | None:
        for action in reply.actions:
            if action.type == "set_expression" and action.value:
                return action.value
        return reply.emotion or None


@dataclass(frozen=True)
class _Evaluation:
    attention_detected: bool
    target_detection: Detection | None
