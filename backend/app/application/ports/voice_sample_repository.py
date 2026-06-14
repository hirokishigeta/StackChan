"""Voice-sample repository port (ABC, ADR-0012).

Lists the pre-generated reference voices the dashboard offers and resolves a
selected sample id to its wav path so the TTS synthesizer can clone it. The
synthesizer (infrastructure) depends on this abstraction, never on a concrete
data source / filesystem layout.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.speech.value_objects import VoiceSample


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
