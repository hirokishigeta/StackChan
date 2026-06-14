"""SpeechSynthesizer backed by Irodori-TTS (ADR-0006, optional heavy deps).

Irodori-TTS is a Japanese, diffusion (rectified-flow)-based TTS with emoji-driven
style control and zero-shot speaker cloning from a reference wav. Its
dependencies (PyTorch / HF checkpoint + codec) are an *optional* extra (``pip
install 'stackchan-backend[tts]'``) and the model is a separate, large download.

Neither torch nor irodori_tts is imported at module import time, so the process
and ``make check`` stay green without them. The runtime is resolved lazily on the
first :meth:`synthesize` (loaded once, then reused); a missing dependency or unset
model path raises :class:`SpeechSynthesisError` (which the WS loop turns into a
text-only fallback, design-spec §13) instead of crashing import.

Real Irodori API (confirmed against ~/Irodori-TTS/irodori_tts/inference_runtime.py
and infer.py)::

    from irodori_tts.inference_runtime import (
        InferenceRuntime, RuntimeKey, SamplingRequest,
    )
    runtime = InferenceRuntime.from_key(RuntimeKey(
        checkpoint=<.safetensors path>, model_device="cuda",
        codec_repo="Aratako/Semantic-DACVAE-Japanese-32dim",
        model_precision="fp32", codec_device="cpu", codec_precision="fp32",
    ))
    result = runtime.synthesize(SamplingRequest(
        text=<styled text(絵文字込み)>, ref_wav=<wav path or None>,
        no_ref=<bool>, num_candidates=1, decode_mode="sequential",
    ))
    # result.audio: float torch.Tensor shaped (channels, samples)
    # result.sample_rate: int (== 48000)

RuntimeKey / SamplingRequest defaults below match the infer.py argparse defaults
(codec_repo, model_precision, codec_precision, num_steps, cfg_scale_*, etc.); we
only override what we configure (checkpoint/device/precision/ref). Paths/device
come from :class:`AppSettings` (CLAUDE.md: no hard-coded paths). The agent
``emotion`` is mapped to an Irodori emoji style via
:mod:`app.infrastructure.tts.emotion_style`.

Speaker-conditioned checkpoints require a reference wav; if
``irodori_reference_wav_path`` is unset we fall back to ``no_ref=True`` so the
runtime can still synthesize an unconditioned voice.
"""

from __future__ import annotations

import struct
from typing import Any

from app.application.ports.speech_synthesizer import SpeechSynthesisError, SpeechSynthesizer
from app.application.ports.voice_config_provider import VoiceConfigProvider
from app.config.settings import AppSettings
from app.domain.speech.value_objects import SynthesizedAudio

from .emotion_style import style_text


class IrodoriTtsSynthesizer(SpeechSynthesizer):
    """Zero-shot Japanese TTS via Irodori-TTS (emoji style control)."""

    def __init__(
        self,
        settings: AppSettings,
        voice_config: VoiceConfigProvider | None = None,
    ) -> None:
        self._settings = settings
        # When wired, caption/base_style are read per-call from the runtime
        # voice config (dashboard override) so a change takes effect on the next
        # synthesize without restart (ADR-0009). Falls back to AppSettings when
        # absent, preserving the original behavior.
        self._voice_config = voice_config
        self._runtime: Any | None = None
        # SamplingRequest class, resolved lazily alongside the runtime. Tests may
        # inject both ``_runtime`` and ``_request_cls`` to exercise synthesize()
        # without the optional heavy deps.
        self._request_cls: Any | None = None

    def _load_runtime(self) -> Any:
        """Lazily build the InferenceRuntime once and cache it.

        torch / irodori_tts are imported here (not at module import) so the
        package stays importable without the optional heavy deps.
        """
        if self._runtime is not None:
            return self._runtime
        try:
            import torch  # noqa: F401
            from irodori_tts.inference_runtime import (
                InferenceRuntime,
                RuntimeKey,
                SamplingRequest,
            )
        except ImportError as exc:  # pragma: no cover - optional heavy dep
            raise SpeechSynthesisError(
                "Irodori-TTS is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[tts]' (requires PyTorch)."
            ) from exc

        model_path = self._settings.irodori_model_path
        if not model_path:
            raise SpeechSynthesisError(
                "Irodori-TTS model path is not configured. Set "
                "STACKCHAN_IRODORI_MODEL_PATH (ADR-0006)."
            )
        model_path = self._resolve_checkpoint(model_path)

        try:
            self._runtime = InferenceRuntime.from_key(
                RuntimeKey(
                    checkpoint=model_path,
                    model_device=self._settings.irodori_device,
                    codec_repo=self._settings.irodori_codec_repo,
                    model_precision=self._settings.irodori_model_precision,
                    codec_device=self._settings.irodori_codec_device,
                    codec_precision=self._settings.irodori_codec_precision,
                )
            )
        except Exception as exc:  # noqa: BLE001 - normalize load errors
            raise SpeechSynthesisError(f"Irodori-TTS runtime load failed: {exc}") from exc
        self._request_cls = SamplingRequest
        return self._runtime

    @staticmethod
    def _resolve_checkpoint(model_path: str) -> str:
        """Return a local ``.safetensors`` path, downloading from HF if needed.

        ``irodori_model_path`` may be either a local file path or a Hugging Face
        repo id (e.g. ``Aratako/Irodori-TTS-600M-v3-VoiceDesign``). For a repo
        id we fetch ``model.safetensors`` via ``hf_hub_download`` (cached). A
        value that already exists on disk is returned unchanged.
        """
        import os

        if os.path.exists(model_path):
            return model_path
        # Heuristic: "<org>/<repo>" with no path separator beyond the single
        # slash and no extension -> treat as an HF repo id.
        if "/" in model_path and not model_path.endswith(".safetensors"):
            try:
                from huggingface_hub import hf_hub_download

                local = hf_hub_download(repo_id=model_path, filename="model.safetensors")
                return str(local)
            except Exception as exc:  # noqa: BLE001 - normalize download errors
                raise SpeechSynthesisError(
                    f"Irodori-TTS checkpoint download failed for repo '{model_path}': {exc}"
                ) from exc
        return model_path

    def warm_up(self) -> None:
        """Preload the InferenceRuntime so the first turn pays no load latency.

        Never raises (per the port contract): on failure the first
        :meth:`synthesize` will retry the load and surface the error there.
        """
        try:
            self._load_runtime()
        except SpeechSynthesisError:
            return

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        runtime = self._load_runtime()
        request_cls: Any = self._request_cls
        if request_cls is None:  # pragma: no cover - load_runtime always sets it
            from irodori_tts.inference_runtime import SamplingRequest

            request_cls = SamplingRequest

        # Read caption / base_style from the runtime voice config when wired
        # (dashboard override, ADR-0009); else fall back to AppSettings defaults.
        # Reference wav precedence (ADR-0012): the selected voice sample's wav
        # (cloned to fix the timbre) -> the static irodori_reference_wav_path ->
        # None (no_ref). Resolved per-call from the runtime voice config.
        selected_reference: str | None = None
        if self._voice_config is not None:
            voice = self._voice_config.current_voice()
            base_style = voice.irodori_base_style
            caption_value = voice.irodori_caption
            selected_reference = self._voice_config.selected_reference_wav()
        else:
            base_style = self._settings.irodori_base_style
            caption_value = self._settings.irodori_caption

        styled = style_text(text=text, emotion=emotion, base_style=base_style)
        reference = selected_reference or self._settings.irodori_reference_wav_path or None
        # Production policy (owner decision): caption is used only when *creating*
        # a reference voice. When a reference wav is set we clone it with NO
        # caption, because mixing caption + ref drifts the timbre between turns;
        # ref-only cloning is the most stable. Caption only applies in the
        # no-ref path (and at ref-generation time, which passes a caption).
        caption = None if reference is not None else (caption_value or None)
        # Fix the sampling seed so the voice (speaker timbre) is consistent across
        # turns (esp. for the no-ref path, where VoiceDesign otherwise samples a
        # fresh speaker each call). Cloning a reference also benefits from a fixed
        # seed for deterministic prosody.
        seed = self._settings.irodori_seed
        try:
            result = runtime.synthesize(
                request_cls(
                    text=styled,
                    caption=caption,
                    ref_wav=reference,
                    no_ref=reference is None,
                    num_candidates=1,
                    decode_mode="sequential",
                    seed=seed,
                )
            )
        except Exception as exc:  # noqa: BLE001 - normalize engine errors
            raise SpeechSynthesisError(f"Irodori-TTS synthesis failed: {exc}") from exc

        pcm = self._float_to_pcm16(result.audio)
        sample_rate = int(getattr(result, "sample_rate", self._settings.irodori_sample_rate))
        return SynthesizedAudio(pcm=pcm, sample_rate=sample_rate)

    @staticmethod
    def _float_to_pcm16(waveform: Any) -> bytes:
        """Convert a float waveform to little-endian PCM16 mono bytes.

        ``result.audio`` is a float torch.Tensor shaped ``(channels, samples)``
        (often ``(1, N)``). We flatten across channels to mono samples; values
        are clamped to [-1, 1] before scaling. Works for torch tensors, numpy
        arrays, and plain (nested) lists without importing torch/numpy here.
        """
        try:
            samples = waveform.detach().cpu().tolist()  # torch tensor
        except AttributeError:
            try:
                samples = waveform.tolist()  # numpy array
            except AttributeError:
                samples = list(waveform)
        flat: list[float] = _flatten(samples)
        ints = [max(-32768, min(32767, round(_clamp(s) * 32767.0))) for s in flat]
        return struct.pack(f"<{len(ints)}h", *ints)


def _clamp(value: float) -> float:
    v = float(value)
    if v > 1.0:
        return 1.0
    if v < -1.0:
        return -1.0
    return v


def _flatten(values: Any) -> list[float]:
    if isinstance(values, (list, tuple)):
        out: list[float] = []
        for v in values:
            out.extend(_flatten(v))
        return out
    return [values]
