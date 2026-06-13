"""Provider -> concrete SpeechSynthesizer resolution via a registry.

Mirrors the speech/audio registries (CLAUDE.md: registry, not ``if`` branching).
Selected by ``STACKCHAN_DEFAULT_TTS_PROVIDER``. ``irodori`` is the real provider
(ADR-0006); ``dummy`` is the default for tests / no-model environments so the
process and ``make check`` run without heavy deps. Construction never loads
torch or models — those are lazy (see :class:`IrodoriTtsSynthesizer`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.application.ports.voice_config_provider import VoiceConfigProvider
from app.config.settings import AppSettings

from .dummy_speech_synthesizer import DummySpeechSynthesizer
from .irodori_tts_synthesizer import IrodoriTtsSynthesizer

SynthesizerBuilder = Callable[[AppSettings, VoiceConfigProvider | None], SpeechSynthesizer]


def _build_dummy(
    settings: AppSettings, voice_config: VoiceConfigProvider | None
) -> SpeechSynthesizer:
    return DummySpeechSynthesizer(settings)


def _build_irodori(
    settings: AppSettings, voice_config: VoiceConfigProvider | None
) -> SpeechSynthesizer:
    return IrodoriTtsSynthesizer(settings, voice_config)


_BUILDERS: dict[str, SynthesizerBuilder] = {
    "dummy": _build_dummy,
    "irodori": _build_irodori,
}

_DEFAULT = "dummy"


def build_speech_synthesizer(
    settings: AppSettings, voice_config: VoiceConfigProvider | None = None
) -> SpeechSynthesizer:
    """Resolve and construct the configured downlink SpeechSynthesizer.

    The provider is selected by the *effective* TTS provider when a runtime
    voice config is supplied (dashboard override, ADR-0009); otherwise by the
    ``AppSettings`` default. This keeps a provider change from the dashboard
    requiring only a synthesizer rebuild, not an if-branch (CLAUDE.md).
    """
    provider = settings.default_tts_provider
    if voice_config is not None:
        provider = voice_config.current_voice().tts_provider
    builder = _BUILDERS.get(provider, _BUILDERS[_DEFAULT])
    return builder(settings, voice_config)
