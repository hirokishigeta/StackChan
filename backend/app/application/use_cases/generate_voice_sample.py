"""Use case: mint a reference voice and persist it as a selectable sample.

Drives the dashboard "ref生成" flow (ADR-0013): synthesize a clean voice from a
natural-language caption + example text on the GPU, then store the PCM as a new
``VoiceSample`` so it appears in the existing picker. Business logic lives here,
not in the route (CLAUDE.md): the route only maps domain errors to HTTP status.
"""

from __future__ import annotations

from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.domain.speech.value_objects import VoiceSample


class GenerateVoiceSampleUseCase:
    """Generate a reference voice and save it as a new selectable sample."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        repository: VoiceSampleRepository,
    ) -> None:
        self._synthesizer = synthesizer
        self._repository = repository

    def execute(
        self,
        *,
        sample_id: str,
        caption: str,
        text: str,
        label: str | None = None,
    ) -> VoiceSample:
        """Synthesize from ``caption`` then persist as ``sample_id``.

        Raises :class:`SpeechSynthesisError` if the engine is unavailable / fails,
        and :class:`InvalidSampleIdError` / :class:`DuplicateSampleError` from the
        repository on a bad or already-taken id. The caller maps these to HTTP.
        """
        audio = self._synthesizer.generate_reference(text=text, caption=caption)
        return self._repository.save(
            sample_id=sample_id,
            pcm=audio.pcm,
            sample_rate=audio.sample_rate,
            label=label,
            caption=caption,
        )
