"""Tests for SherpaOnnxSpeechRecognizer loader selection and decoding.

``sherpa_onnx`` is an optional native dependency and is NOT installed for
``make check``; these tests inject a fake module into ``sys.modules`` so the
lazy import resolves without the real binding.
"""

from __future__ import annotations

import struct
import sys
import types
from typing import Any

import pytest
from app.config.settings import AppSettings
from app.domain.speech.entities import SpeechRecognitionConfig
from app.infrastructure.speech.sherpa_onnx_speech_recognizer import (
    SherpaOnnxConfigError,
    SherpaOnnxSpeechRecognizer,
)


class _FakeStream:
    def __init__(self, text: str) -> None:
        self.result = types.SimpleNamespace(text=text)
        self.accepted: tuple[int, list[float]] | None = None

    def accept_waveform(self, sample_rate: int, samples: list[float]) -> None:
        self.accepted = (sample_rate, samples)


class _FakeRecognizer:
    def __init__(self, text: str) -> None:
        self._text = text

    def create_stream(self) -> _FakeStream:
        return _FakeStream(self._text)

    def decode_stream(self, stream: _FakeStream) -> None:  # noqa: D401
        pass


class _FakeOfflineRecognizer:
    transducer_calls: list[dict[str, Any]] = []
    nemo_calls: list[dict[str, Any]] = []
    text = "こんにちは"

    @classmethod
    def from_transducer(cls, **kwargs: Any) -> _FakeRecognizer:
        cls.transducer_calls.append(kwargs)
        return _FakeRecognizer(cls.text)

    @classmethod
    def from_nemo_ctc(cls, **kwargs: Any) -> _FakeRecognizer:
        cls.nemo_calls.append(kwargs)
        return _FakeRecognizer(cls.text)


@pytest.fixture
def fake_sherpa(monkeypatch: pytest.MonkeyPatch) -> type[_FakeOfflineRecognizer]:
    _FakeOfflineRecognizer.transducer_calls = []
    _FakeOfflineRecognizer.nemo_calls = []
    module = types.ModuleType("sherpa_onnx")
    module.OfflineRecognizer = _FakeOfflineRecognizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    return _FakeOfflineRecognizer


def _settings(**overrides: Any) -> AppSettings:
    return AppSettings(_env_file=None, **overrides)


def _pcm16(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_nemo_ctc_loader_used_when_nemo_path_set(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    settings = _settings(
        sherpa_nemo_model_path="/models/parakeet/model.int8.onnx",
        sherpa_tokens_path="/models/parakeet/tokens.txt",
        sherpa_num_threads=2,
    )
    recognizer = SherpaOnnxSpeechRecognizer(settings)
    recognizer._load_recognizer()

    assert fake_sherpa.transducer_calls == []
    assert len(fake_sherpa.nemo_calls) == 1
    call = fake_sherpa.nemo_calls[0]
    assert call["model"] == "/models/parakeet/model.int8.onnx"
    assert call["tokens"] == "/models/parakeet/tokens.txt"
    assert call["num_threads"] == 2


def test_transducer_loader_used_when_only_transducer_paths_set(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    settings = _settings(
        sherpa_tokens_path="/m/tokens.txt",
        sherpa_encoder_path="/m/encoder.onnx",
        sherpa_decoder_path="/m/decoder.onnx",
        sherpa_joiner_path="/m/joiner.onnx",
    )
    recognizer = SherpaOnnxSpeechRecognizer(settings)
    recognizer._load_recognizer()

    assert fake_sherpa.nemo_calls == []
    assert len(fake_sherpa.transducer_calls) == 1
    call = fake_sherpa.transducer_calls[0]
    assert call["encoder"] == "/m/encoder.onnx"
    assert call["joiner"] == "/m/joiner.onnx"


def test_missing_both_raises_config_error(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    recognizer = SherpaOnnxSpeechRecognizer(_settings())
    with pytest.raises(SherpaOnnxConfigError):
        recognizer._load_recognizer()


def test_nemo_without_tokens_falls_through_to_config_error(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    # nemo model set but no tokens and no full transducer set -> error.
    recognizer = SherpaOnnxSpeechRecognizer(_settings(sherpa_nemo_model_path="/m/model.onnx"))
    with pytest.raises(SherpaOnnxConfigError):
        recognizer._load_recognizer()
    assert fake_sherpa.nemo_calls == []


@pytest.mark.anyio
async def test_recognize_returns_decoded_text_nemo(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    settings = _settings(
        sherpa_nemo_model_path="/m/model.onnx",
        sherpa_tokens_path="/m/tokens.txt",
    )
    recognizer = SherpaOnnxSpeechRecognizer(settings)
    result = await recognizer.recognize(
        audio=_pcm16([0, 16384, -16384, 32767]),
        config=SpeechRecognitionConfig(language="ja"),
    )
    assert result.text == "こんにちは"
    assert result.language == "ja"


@pytest.mark.anyio
async def test_recognize_returns_decoded_text_transducer(
    fake_sherpa: type[_FakeOfflineRecognizer],
) -> None:
    settings = _settings(
        sherpa_tokens_path="/m/tokens.txt",
        sherpa_encoder_path="/m/encoder.onnx",
        sherpa_decoder_path="/m/decoder.onnx",
        sherpa_joiner_path="/m/joiner.onnx",
    )
    recognizer = SherpaOnnxSpeechRecognizer(settings)
    result = await recognizer.recognize(
        audio=_pcm16([1, 2, 3, 4]),
        config=SpeechRecognitionConfig(language="ja"),
    )
    assert result.text == "こんにちは"
