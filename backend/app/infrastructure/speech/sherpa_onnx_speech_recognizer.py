"""SpeechRecognizer backed by sherpa-onnx (optional native dependency).

``sherpa-onnx`` is an optional extra (``pip install
'stackchan-backend[sherpa]'``) and the model files are a separate, large
download. Neither is imported/loaded at module import time, so the process and
``make check`` stay green without them. The recognizer and its models are
resolved lazily on first :meth:`recognize`; a missing binding or unset model
path raises a clear error instead of crashing import.

Model paths come from :class:`AppSettings` (CLAUDE.md: no hard-coded paths).
TODO(issue#7): wire streaming / partial results into the WS loop once a
streaming model is configured (docs/backend-protocol.md §6 turn management).
"""

from __future__ import annotations

import struct
from typing import Any

from app.application.ports.speech_recognizer import SpeechRecognizer
from app.config.settings import AppSettings
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import SpeechRecognitionResult


class SherpaOnnxConfigError(RuntimeError):
    """Raised when sherpa-onnx is unavailable or misconfigured."""


class SherpaOnnxSpeechRecognizer(SpeechRecognizer):
    """Offline recognizer using sherpa-onnx (transducer/paraformer/whisper)."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._recognizer: Any | None = None

    def _load_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        try:
            import sherpa_onnx
        except ImportError as exc:  # pragma: no cover - optional native dep
            raise SherpaOnnxConfigError(
                "sherpa-onnx is not installed. Install the optional extra: "
                "pip install 'stackchan-backend[sherpa]'."
            ) from exc

        tokens = self._settings.sherpa_tokens_path
        encoder = self._settings.sherpa_encoder_path
        decoder = self._settings.sherpa_decoder_path
        joiner = self._settings.sherpa_joiner_path
        if not (tokens and encoder and decoder and joiner):
            raise SherpaOnnxConfigError(
                "sherpa-onnx model paths are not configured. Set "
                "STACKCHAN_SHERPA_TOKENS_PATH / _ENCODER_PATH / _DECODER_PATH / "
                "_JOINER_PATH (docs/backend-protocol.md §3.2)."
            )
        # OfflineRecognizer keeps wiring minimal for #7-a; a streaming model can
        # be swapped in later (TODO above).
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=self._settings.sherpa_num_threads,
        )
        return self._recognizer

    async def recognize(
        self,
        *,
        audio: bytes,
        config: SpeechRecognitionConfig,
    ) -> SpeechRecognitionResult:
        recognizer = self._load_recognizer()
        samples = self._pcm16_to_float(audio)
        stream = recognizer.create_stream()
        stream.accept_waveform(self._settings.sherpa_sample_rate, samples)
        recognizer.decode_stream(stream)
        text = str(stream.result.text)
        return SpeechRecognitionResult(text=text, language=config.language, confidence=1.0)

    @staticmethod
    def _pcm16_to_float(audio: bytes) -> list[float]:
        """Convert little-endian PCM16 mono bytes to normalized float samples."""
        count = len(audio) // 2
        if count == 0:
            return []
        ints = struct.unpack(f"<{count}h", audio[: count * 2])
        return [s / 32768.0 for s in ints]
