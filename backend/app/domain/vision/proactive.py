"""Proactive-talk gating + VisionState transitions (design-spec §6.3–§6.5).

Pure decision logic. The "current time" and per-device history are passed in by
the application layer (testability / CLAUDE.md domain rule) — nothing here reads
a clock or stores mutable state.

The guard prevents "目が合ったら即連発" (design-spec §6): every proactive talk
must pass enabled + cooldown + per-day cap + not-in-conversation (unless
interruption allowed) before AgentGateway.proactive() is called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .entities import ProactiveTalkConfig
from .value_objects import VisionState


class ProactiveDecision(StrEnum):
    """Why a proactive talk was allowed or suppressed (for logging / tests)."""

    ALLOWED = "allowed"
    DISABLED = "disabled"
    COOLDOWN = "cooldown"
    MAX_PER_DAY = "max_per_day"
    IN_CONVERSATION = "in_conversation"


@dataclass(frozen=True)
class ProactiveTalkHistory:
    """Per-device proactive-talk history used to apply cooldown / daily cap.

    Immutable; :meth:`record` returns an updated copy. Persisted in-memory by the
    application layer for this phase (TODO(issue#8): durable store if needed).
    """

    last_talk_at: datetime | None = None
    talks_today: int = 0
    # The date (UTC, ``YYYY-MM-DD``) ``talks_today`` is counted for; lets the
    # daily cap reset without a background job.
    counted_date: str | None = None

    def normalized(self, now: datetime) -> ProactiveTalkHistory:
        """Reset the daily counter when ``now`` is a new day."""
        today = now.date().isoformat()
        if self.counted_date != today:
            return ProactiveTalkHistory(
                last_talk_at=self.last_talk_at, talks_today=0, counted_date=today
            )
        return self

    def record(self, now: datetime) -> ProactiveTalkHistory:
        """Return history after a talk fired at ``now``."""
        base = self.normalized(now)
        return ProactiveTalkHistory(
            last_talk_at=now,
            talks_today=base.talks_today + 1,
            counted_date=now.date().isoformat(),
        )

    def seconds_since_last(self, now: datetime) -> float | None:
        if self.last_talk_at is None:
            return None
        return (now - self.last_talk_at).total_seconds()


def evaluate_proactive_talk(
    *,
    config: ProactiveTalkConfig,
    history: ProactiveTalkHistory,
    now: datetime,
    conversation_active: bool,
) -> ProactiveDecision:
    """Decide whether a proactive talk may fire now (design-spec §6.3 / §6.4).

    All conditions must hold. ``disabled_in_focus_mode`` / ``disabled_at_night``
    are config flags; the actual focus/night signals are device/runtime inputs
    not modelled in this phase — TODO(issue#8): pass them in and gate here.
    """
    if not config.enabled:
        return ProactiveDecision.DISABLED

    if conversation_active and not config.allow_during_conversation:
        return ProactiveDecision.IN_CONVERSATION

    normalized = history.normalized(now)
    if normalized.talks_today >= config.max_count_per_day:
        return ProactiveDecision.MAX_PER_DAY

    elapsed = normalized.seconds_since_last(now)
    if elapsed is not None and elapsed < config.cooldown_seconds:
        return ProactiveDecision.COOLDOWN

    return ProactiveDecision.ALLOWED


# Allowed VisionState transitions (design-spec §6.5). Kept minimal: the happy
# path plus the documented "lost target → Idle" edges. Unknown edges are
# rejected so callers can detect logic errors.
_TRANSITIONS: dict[VisionState, frozenset[VisionState]] = {
    VisionState.IDLE: frozenset({VisionState.MOTION_DETECTED, VisionState.FACE_DETECTED}),
    VisionState.MOTION_DETECTED: frozenset({VisionState.FACE_DETECTED, VisionState.IDLE}),
    VisionState.FACE_DETECTED: frozenset(
        {VisionState.TRACKING, VisionState.ATTENTION_DETECTED, VisionState.IDLE}
    ),
    VisionState.TRACKING: frozenset(
        {VisionState.ATTENTION_DETECTED, VisionState.FACE_DETECTED, VisionState.IDLE}
    ),
    VisionState.ATTENTION_DETECTED: frozenset(
        {VisionState.CONVERSATION, VisionState.FACE_DETECTED, VisionState.IDLE}
    ),
    VisionState.CONVERSATION: frozenset({VisionState.IDLE, VisionState.FACE_DETECTED}),
}


def can_transition(current: VisionState, target: VisionState) -> bool:
    """Whether ``current -> target`` is an allowed VisionState edge (§6.5)."""
    if current == target:
        return True
    return target in _TRANSITIONS.get(current, frozenset())


def next_state(
    *,
    current: VisionState,
    face_present: bool,
    attention_detected: bool,
    conversation_active: bool,
) -> VisionState:
    """Derive the next VisionState from frame signals (design-spec §6.5).

    Minimal mapping for the backend's per-frame evaluation. Motion detection is
    a device-side concern (TODO(issue#5)); the backend enters at FaceDetected.
    """
    if conversation_active:
        return VisionState.CONVERSATION
    if not face_present:
        return VisionState.IDLE
    if attention_detected:
        return VisionState.ATTENTION_DETECTED
    return VisionState.FACE_DETECTED


@dataclass
class VisionSession:
    """Mutable per-device runtime state for attention tracking.

    Held in memory by the application layer for this phase. Tracks the current
    VisionState, how long the attention candidate has held, and proactive-talk
    history (cooldown / daily cap).
    """

    state: VisionState = VisionState.IDLE
    candidate_since: datetime | None = None
    history: ProactiveTalkHistory = field(default_factory=ProactiveTalkHistory)

    def candidate_duration_ms(self, now: datetime) -> int:
        if self.candidate_since is None:
            return 0
        return int((now - self.candidate_since).total_seconds() * 1000)
