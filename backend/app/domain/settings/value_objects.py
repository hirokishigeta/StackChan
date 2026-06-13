"""Settings value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DisplaySettings:
    """Screen / device basic settings preserved on the device (design-spec §3.1)."""

    brightness: int = 80
    theme: str = "default"
    volume: int = 70


@dataclass(frozen=True)
class ServerVoiceSettings:
    """Server-global, runtime-mutable TTS voice configuration (ADR-0009).

    These are *not* per-device: they describe the single voice persona the
    backend synthesizes with. The effective value is the persisted dashboard
    override layered onto the ``AppSettings`` / env defaults (see
    ``ManageServerSettingsUseCase``). The synthesizer reads them per-call so a
    dashboard change takes effect on the next utterance without a restart.
    """

    tts_provider: str = "dummy"
    irodori_caption: str = ""
    irodori_base_style: str = ""
