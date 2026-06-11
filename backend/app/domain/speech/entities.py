"""Speech recognition entities (design-spec §4.4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechRecognitionConfig:
    """Speech recognition configuration."""

    provider: str = "dummy"
    model_name: str = "dummy-asr"
    language: str = "ja"
    vad_enabled: bool = True
    noise_reduction_enabled: bool = True
    streaming_enabled: bool = False


@dataclass(frozen=True)
class ConversationTurnConfig:
    """Conversation turn / barge-in configuration (design-spec §7)."""

    barge_in_enabled: bool = False
    aec_enabled: bool = False
    vad_threshold: float = 0.5
    vad_threshold_while_speaking: float = 0.7
    min_interruption_duration_ms: int = 400
    end_of_turn_silence_ms: int = 800
    semantic_end_of_turn_enabled: bool = False
    max_utterance_duration_ms: int = 15000
    interrupt_behavior: str = "stop"  # stop / fade_out / finish_sentence
