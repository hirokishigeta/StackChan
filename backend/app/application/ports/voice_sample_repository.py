"""Voice-sample repository port (ABC, ADR-0012).

Lists the pre-generated reference voices the dashboard offers and resolves a
selected sample id to its wav path so the TTS synthesizer can clone it. The
synthesizer (infrastructure) depends on this abstraction, never on a concrete
data source / filesystem layout.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.value_objects import VoiceSample


class InvalidSampleIdError(ValueError):
    """Raised when a sample id is not a safe slug (path separators / traversal)."""


class DuplicateSampleError(ValueError):
    """Raised when saving a sample id that already exists (overwrite rejected)."""


class VoiceSampleRepository(ABC):
    """Supplies the catalogue of selectable reference voices."""

    @abstractmethod
    def list_samples(self) -> list[VoiceSample]:
        """Return all available voice samples (id + label)."""
        raise NotImplementedError

    @abstractmethod
    def resolve_wav_path(self, sample_id: str) -> str | None:
        """Return the absolute wav path for ``sample_id`` or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def save(
        self,
        *,
        sample_id: str,
        pcm: bytes,
        sample_rate: int,
        label: str | None = None,
        caption: str | None = None,
    ) -> VoiceSample:
        """Persist mono PCM16 ``pcm`` as a new selectable sample (ADR-0013).

        Writes ``<sample_id>.wav`` into the samples dir and records ``label`` /
        ``caption`` in the directory metadata so the sample is immediately
        listable. ``sample_id`` must be a safe slug (no path separators /
        traversal); implementations raise :class:`InvalidSampleIdError` for a bad
        id and :class:`DuplicateSampleError` if the id already exists (overwrite
        is intentionally rejected). Returns the persisted :class:`VoiceSample`.
        """
        raise NotImplementedError
