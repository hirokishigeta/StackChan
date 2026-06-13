"""Speech synthesizer port (ABC) for downlink TTS (Issue #7-b).

The WebSocket audio server turns an agent reply (text + emotion) into downlink
audio between the ``tts.start`` and ``tts.stop`` control messages (see
``docs/backend-protocol.md`` §2.2 / §4.1). The concrete TTS engine (Irodori-TTS,
ADR-0006) pulls in heavy optional dependencies (PyTorch / HF checkpoints), so the
WS handler depends only on this abstraction (CLAUDE.md: ports = ABC,
infrastructure = concrete). Tests inject a fake.

Synthesis is sentence-level for now: ``synthesize`` returns the whole utterance
as one PCM buffer. The signature returns the produced sample rate alongside the
PCM so the caller can resample to the negotiated downlink rate without guessing
(Irodori emits 48 kHz; downlink default is 24 kHz, ADR-0006).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.value_objects import SynthesizedAudio


class SpeechSynthesisError(RuntimeError):
    """Raised when synthesis fails or the TTS engine is unavailable.

    The WS loop catches this and falls back to a text-only turn (design-spec
    §13): a missing engine or a single failed synthesis must not break the
    session. Adapters wrap engine-specific failures in this type so callers do
    not depend on transport/runtime details.
    """


class SpeechSynthesizer(ABC):
    """Abstraction over a downlink TTS engine (text [+emotion] -> PCM)."""

    @abstractmethod
    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        """Synthesize ``text`` into mono PCM16, optionally styled by ``emotion``.

        ``emotion`` is one of the agent vocabulary values (neutral / happy / sad
        / angry / curious / surprised / sleepy); adapters map it to engine-side
        style controls. Implementations raise :class:`SpeechSynthesisError` on
        failure instead of leaking engine-specific exceptions.
        """
        raise NotImplementedError

    def warm_up(self) -> None:
        """Eagerly load any heavy runtime so the first turn isn't slow.

        Optional: the default is a no-op (lightweight engines need nothing).
        Heavy engines (Irodori-TTS) override this to load the model ahead of the
        first :meth:`synthesize`, so a user's first utterance doesn't pay the
        one-time model-load latency (which can exceed the device reply timeout).
        Must not raise: a failed warm-up just defers loading to the first call.
        """
        return None
