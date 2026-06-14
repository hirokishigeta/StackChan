"""Wake word entities (design-spec §4.4 / §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .value_objects import EndWordEntry, WakeWordEntry

# Default end-of-conversation phrases (ADR-0016). Single source of truth: the
# per-device ``EndWordConfig`` default below and the global fallback list in
# ``AppSettings.conversation_end_words`` both derive from this tuple, so the
# sensible JP starter list is declared exactly once.
DEFAULT_END_WORD_PHRASES: tuple[str, ...] = (
    "ばいばい",
    "バイバイ",
    "またね",
    "じゃあね",
    "おやすみ",
    "もういいよ",
    "もう大丈夫",
    "終わりで",
    "またあとで",
)

# Default wake words for a freshly registered device (design-spec §8.1).
# Detection runs on-device (esp-sr / WakeNet, see ADR-0011); the backend only
# stores and serves this list. These are sensible starter phrases the user can
# edit / extend from the dashboard, not a hard-coded behavioural constant.
DEFAULT_WAKE_WORDS: tuple[WakeWordEntry, ...] = (
    WakeWordEntry(id="ww-default-1", phrase="スタックチャン"),
    WakeWordEntry(id="ww-default-2", phrase="ねえスタックチャン"),
)


@dataclass(frozen=True)
class WakeWordConfig:
    """Wake word configuration. Supports multiple wake words (design-spec §8.1).

    Backend detection is gated by ``AppSettings.wake_word_gate_enabled`` and
    on-device wake uses a fixed compiled model, so the legacy ``detection_method``
    / ``max_local_active`` knobs were unused and have been removed (ADR-0017).
    ``enabled`` is retained for the per-device wake-word toggle.
    """

    enabled: bool = True
    wake_words: tuple[WakeWordEntry, ...] = field(default_factory=lambda: DEFAULT_WAKE_WORDS)


# Default per-device end words for a freshly registered device (ADR-0016),
# derived from the shared ``DEFAULT_END_WORD_PHRASES`` so the literal is not
# duplicated. The user can edit / extend these from the dashboard.
DEFAULT_END_WORDS: tuple[EndWordEntry, ...] = tuple(
    EndWordEntry(id=f"ew-default-{i + 1}", phrase=phrase)
    for i, phrase in enumerate(DEFAULT_END_WORD_PHRASES)
)


@dataclass(frozen=True)
class EndWordConfig:
    """Per-device end-of-conversation words (ADR-0016).

    While the backend wake gate is engaged (ADR-0014), an utterance containing
    any enabled end word ends the conversation and returns the device to
    wake-waiting. When a device has no end words configured the backend falls
    back to the global ``AppSettings.conversation_end_words`` list.
    """

    end_words: tuple[EndWordEntry, ...] = field(default_factory=lambda: DEFAULT_END_WORDS)
