"""Attention detection + proactive talk tests (design-spec §6).

All external deps are faked: a stub VisionRecognizer returns scripted
detections, the AgentGateway is the dummy, and the clock is injected so
cooldown / daily-cap / continuity are deterministic (no native deps / no real
OpenCV — CLAUDE.md).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.application.ports.agent_gateway import AgentError, AgentGateway
from app.application.ports.vision_recognizer import VisionRecognizer
from app.application.use_cases.detect_attention import DetectAttentionUseCase, SessionStore
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent
from app.domain.settings.entities import BotSettings
from app.domain.vision.entities import (
    AttentionDetectionConfig,
    ProactiveTalkConfig,
    VisionRecognitionConfig,
)
from app.domain.vision.proactive import (
    ProactiveDecision,
    can_transition,
    next_state,
)
from app.domain.vision.value_objects import (
    BoundingBox,
    Detection,
    TrackingTarget,
    VisionDetectionResult,
    VisionState,
)
from app.infrastructure.agent.dummy_agent_gateway import DummyAgentGateway
from app.infrastructure.persistence.sqlite_settings_repository import SqliteSettingsRepository

DEVICE = "cores3-001"
# 320x240 frame; a centred, large, confident face.
CENTERED_FACE = Detection(
    type="face", bbox=BoundingBox(x=128, y=88, width=64, height=64), confidence=0.9
)
# Off-centre face (top-left corner).
OFFSET_FACE = Detection(
    type="face", bbox=BoundingBox(x=0, y=0, width=64, height=64), confidence=0.9
)
# Centred but tiny face (< 15% of 320 width).
SMALL_FACE = Detection(
    type="face", bbox=BoundingBox(x=150, y=110, width=20, height=20), confidence=0.9
)
# Centred, large, but low-confidence.
UNSURE_FACE = Detection(
    type="face", bbox=BoundingBox(x=128, y=88, width=64, height=64), confidence=0.3
)


class FakeVisionRecognizer(VisionRecognizer):
    """Returns scripted results, one per call (last repeats)."""

    def __init__(self, results: list[VisionDetectionResult]) -> None:
        self._results = results
        self.calls = 0

    async def detect(
        self, *, image: bytes, config: VisionRecognitionConfig
    ) -> VisionDetectionResult:
        idx = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[idx]


class FailingVisionRecognizer(VisionRecognizer):
    async def detect(
        self, *, image: bytes, config: VisionRecognitionConfig
    ) -> VisionDetectionResult:
        raise RuntimeError("decode failed")


class FailingAgentGateway(AgentGateway):
    async def chat(self, *, message: str, profile: AgentProfile, context=None) -> AgentReply:  # type: ignore[no-untyped-def]
        raise AgentError("boom")

    async def proactive(self, *, event: ProactiveEvent, profile: AgentProfile) -> AgentReply:
        raise AgentError("boom")


class RecordingPublisher:
    """Captures published commands (no ABC import needed for the test)."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, object]]] = []

    async def publish_command(self, *, device_id: str, command) -> None:  # type: ignore[no-untyped-def]
        self.commands.append((command.type, command.payload))


def _result(*detections: Detection, target: TrackingTarget | None = None) -> VisionDetectionResult:
    return VisionDetectionResult(detections=tuple(detections), tracking_target=target)


def _repo(tmp_path: object) -> SqliteSettingsRepository:
    return SqliteSettingsRepository(f"sqlite:///{tmp_path}/attn.db")  # type: ignore[str-bytes-safe]


def _store_settings(
    repo: SqliteSettingsRepository,
    *,
    attention: AttentionDetectionConfig | None = None,
    proactive: ProactiveTalkConfig | None = None,
) -> None:
    settings = BotSettings(
        device_id=DEVICE,
        vision=VisionRecognitionConfig(resolution="320x240"),
        attention=attention or AttentionDetectionConfig(enabled=True, attention_duration_ms=1500),
        proactive_talk=proactive or ProactiveTalkConfig(enabled=True, cooldown_seconds=300),
    )
    repo.save_settings(settings)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _use_case(
    tmp_path: object,
    *,
    recognizer: VisionRecognizer,
    clock: _Clock,
    gateway: AgentGateway | None = None,
    publisher: RecordingPublisher | None = None,
    attention: AttentionDetectionConfig | None = None,
    proactive: ProactiveTalkConfig | None = None,
) -> tuple[DetectAttentionUseCase, RecordingPublisher]:
    repo = _repo(tmp_path)
    _store_settings(repo, attention=attention, proactive=proactive)
    pub = publisher or RecordingPublisher()
    use_case = DetectAttentionUseCase(
        recognizer,
        repo,
        gateway or DummyAgentGateway(),
        pub,  # type: ignore[arg-type]
        sessions=SessionStore(),
        now_provider=clock,
    )
    return use_case, pub


def test_vision_state_transitions() -> None:
    # Happy path edges (design-spec §6.5).
    assert can_transition(VisionState.IDLE, VisionState.FACE_DETECTED)
    assert can_transition(VisionState.FACE_DETECTED, VisionState.ATTENTION_DETECTED)
    assert can_transition(VisionState.ATTENTION_DETECTED, VisionState.CONVERSATION)
    # Self transition is always allowed; an illegal jump is rejected.
    assert can_transition(VisionState.IDLE, VisionState.IDLE)
    assert not can_transition(VisionState.IDLE, VisionState.CONVERSATION)


def test_next_state_derivation() -> None:
    assert (
        next_state(
            current=VisionState.IDLE,
            face_present=False,
            attention_detected=False,
            conversation_active=False,
        )
        is VisionState.IDLE
    )
    assert (
        next_state(
            current=VisionState.FACE_DETECTED,
            face_present=True,
            attention_detected=True,
            conversation_active=False,
        )
        is VisionState.ATTENTION_DETECTED
    )
    assert (
        next_state(
            current=VisionState.ATTENTION_DETECTED,
            face_present=True,
            attention_detected=True,
            conversation_active=True,
        )
        is VisionState.CONVERSATION
    )


@pytest.mark.anyio
async def test_centered_face_after_duration_detects_attention(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock)

    # First frame: candidate just started, not yet continuous -> no attention.
    r1 = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r1.attention_detected is False
    assert r1.state is VisionState.FACE_DETECTED

    # After the continuity threshold elapses, the next frame detects attention.
    clock.advance(2.0)
    r2 = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r2.attention_detected is True
    assert r2.state is VisionState.ATTENTION_DETECTED
    assert r2.proactive_decision is ProactiveDecision.ALLOWED
    assert r2.proactive_text  # agent reply text propagated
    # Commands queued: look_at + set_expression + proactive_speak.
    types = [t for t, _ in pub.commands]
    assert types == ["look_at", "set_expression", "proactive_speak"]


@pytest.mark.anyio
async def test_offcenter_face_never_detects_attention(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(OFFSET_FACE)])
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(5.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is False
    assert r.state is VisionState.FACE_DETECTED
    assert pub.commands == []


@pytest.mark.anyio
async def test_small_face_does_not_detect_attention(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(SMALL_FACE)])
    use_case, _ = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(5.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is False


@pytest.mark.anyio
async def test_low_confidence_face_does_not_detect_attention(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(UNSURE_FACE)])
    use_case, _ = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(5.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is False


@pytest.mark.anyio
async def test_no_face_returns_idle(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result()])
    use_case, _ = _use_case(tmp_path, recognizer=rec, clock=clock)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is False
    assert r.state is VisionState.IDLE


@pytest.mark.anyio
async def test_cooldown_suppresses_second_talk(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, pub = _use_case(
        tmp_path,
        recognizer=rec,
        clock=clock,
        proactive=ProactiveTalkConfig(enabled=True, cooldown_seconds=300, max_count_per_day=5),
    )
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(2.0)
    first = await use_case.execute(image=b"x", device_id=DEVICE)
    assert first.proactive_decision is ProactiveDecision.ALLOWED

    # Still within cooldown (300s): attention re-detected but suppressed.
    clock.advance(60.0)
    second = await use_case.execute(image=b"x", device_id=DEVICE)
    assert second.attention_detected is True
    assert second.proactive_decision is ProactiveDecision.COOLDOWN
    # No new commands beyond the first talk's three.
    assert len(pub.commands) == 3

    # After cooldown elapses, it fires again.
    clock.advance(300.0)
    third = await use_case.execute(image=b"x", device_id=DEVICE)
    assert third.proactive_decision is ProactiveDecision.ALLOWED
    assert len(pub.commands) == 6


@pytest.mark.anyio
async def test_max_count_per_day_suppresses(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, _ = _use_case(
        tmp_path,
        recognizer=rec,
        clock=clock,
        proactive=ProactiveTalkConfig(enabled=True, cooldown_seconds=10, max_count_per_day=2),
    )
    # Establish a continuous attention candidate, then re-evaluate past each
    # cooldown so only the daily cap can suppress.
    await use_case.execute(image=b"x", device_id=DEVICE)
    decisions: list[ProactiveDecision | None] = []
    for _ in range(4):
        clock.advance(60.0)  # well past the 10s cooldown each time
        r = await use_case.execute(image=b"x", device_id=DEVICE)
        decisions.append(r.proactive_decision)
    # Only the first two fire; the rest hit the daily cap.
    allowed = [d for d in decisions if d is ProactiveDecision.ALLOWED]
    assert len(allowed) == 2
    assert ProactiveDecision.MAX_PER_DAY in decisions


@pytest.mark.anyio
async def test_conversation_active_suppresses(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE, conversation_active=True)
    clock.advance(2.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE, conversation_active=True)
    assert r.state is VisionState.CONVERSATION
    assert r.proactive_decision is ProactiveDecision.IN_CONVERSATION
    assert pub.commands == []


@pytest.mark.anyio
async def test_disabled_proactive_suppresses(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, pub = _use_case(
        tmp_path,
        recognizer=rec,
        clock=clock,
        proactive=ProactiveTalkConfig(enabled=False),
    )
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(2.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is True
    assert r.proactive_decision is ProactiveDecision.DISABLED
    assert pub.commands == []


@pytest.mark.anyio
async def test_look_at_uses_detection_tracking_target(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    target = TrackingTarget(x=200, y=150)
    rec = FakeVisionRecognizer([_result(CENTERED_FACE, target=target)])
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(2.0)
    await use_case.execute(image=b"x", device_id=DEVICE)
    look_at = next(p for t, p in pub.commands if t == "look_at")
    assert look_at["target"] == {"x": 200, "y": 150}


@pytest.mark.anyio
async def test_look_at_falls_back_to_face_center(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])  # no tracking_target
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock)
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(2.0)
    await use_case.execute(image=b"x", device_id=DEVICE)
    look_at = next(p for t, p in pub.commands if t == "look_at")
    # Centre of bbox (128+32, 88+32).
    assert look_at["target"] == {"x": 160, "y": 120}


@pytest.mark.anyio
async def test_detect_failure_does_not_raise(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    use_case, _ = _use_case(tmp_path, recognizer=FailingVisionRecognizer(), clock=clock)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    assert r.attention_detected is False
    assert r.state is VisionState.IDLE


@pytest.mark.anyio
async def test_agent_failure_does_not_raise_or_consume_cooldown(tmp_path: object) -> None:
    clock = _Clock(datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC))
    rec = FakeVisionRecognizer([_result(CENTERED_FACE)])
    use_case, pub = _use_case(tmp_path, recognizer=rec, clock=clock, gateway=FailingAgentGateway())
    await use_case.execute(image=b"x", device_id=DEVICE)
    clock.advance(2.0)
    r = await use_case.execute(image=b"x", device_id=DEVICE)
    # Attention still detected; talk allowed by guards but agent failed -> no
    # commands queued and cooldown not consumed (a later frame can retry).
    assert r.attention_detected is True
    assert r.proactive_text is None
    assert pub.commands == []
