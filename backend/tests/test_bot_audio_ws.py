"""WebSocket audio endpoint tests (Issue #7-a).

Exercises the xiaozhi-compatible handshake and uplink ASR flow with fakes
(fake AgentGateway / SpeechRecognizer / AudioDecoder) — no native deps, no
models, no network (CLAUDE.md). Verifies:

- hello round-trip (server hello: transport/session_id/audio_params),
- listen.start -> uplink frames -> listen.stop -> stt/llm/tts message stream,
- listen.detect text path,
- abort emits tts.stop and discards the in-progress turn,
- a corrupt audio frame / failing ASR does not break the connection
  (design-spec §13).

The downlink TTS audio frames (#7-b) are covered in test_bot_audio_tts.py; the
flow tests here inject a silent (no-frame) synthesizer so the JSON stream stays
identical to #7-a.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.agent_gateway import AgentError, AgentGateway
from app.application.ports.audio_decoder import AudioDecodeError, AudioDecoder
from app.application.ports.audio_encoder import AudioEncoder
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.application.ports.speech_synthesizer import SpeechSynthesizer
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import (
    AudioFormat,
    SpeechRecognitionResult,
    SynthesizedAudio,
)
from fastapi.testclient import TestClient


class _SilentSynth(SpeechSynthesizer):
    """Produces no PCM, so no downlink audio frames are sent (#7-a JSON only)."""

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        return SynthesizedAudio(pcm=b"", sample_rate=24000)


class _PassThroughEncoder(AudioEncoder):
    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        return [pcm] if pcm else []


class _FakeAsr(SpeechRecognizer):
    def __init__(self, text: str = "おはよう") -> None:
        self.text = text
        self.received: list[bytes] = []

    async def recognize(
        self, *, audio: bytes, config: SpeechRecognitionConfig
    ) -> SpeechRecognitionResult:
        self.received.append(audio)
        return SpeechRecognitionResult(text=self.text, language=config.language, confidence=1.0)


class _FailingAsr(SpeechRecognizer):
    async def recognize(
        self, *, audio: bytes, config: SpeechRecognitionConfig
    ) -> SpeechRecognitionResult:
        raise RuntimeError("boom")


class _FakeDecoder(AudioDecoder):
    """Records frames; returns payload unchanged (treats it as PCM)."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        self.frames.append(payload)
        return payload


class _ExplodingDecoder(AudioDecoder):
    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        raise AudioDecodeError("no codec")


class _FakeAgent(AgentGateway):
    def __init__(self, reply: AgentReply | None = None) -> None:
        self.reply = reply or AgentReply(text="やあ", emotion="happy")
        self.messages: list[str] = []

    async def chat(
        self, *, message: str, profile: AgentProfile, context: dict[str, object] | None = None
    ) -> AgentReply:
        self.messages.append(message)
        return self.reply

    async def proactive(self, *, event: ProactiveEvent, profile: AgentProfile) -> AgentReply:
        return self.reply


class _RaisingAgent(AgentGateway):
    async def chat(
        self, *, message: str, profile: AgentProfile, context: dict[str, object] | None = None
    ) -> AgentReply:
        raise AgentError("down")

    async def proactive(self, *, event: ProactiveEvent, profile: AgentProfile) -> AgentReply:
        raise AgentError("down")


# version 0 = raw payload (no binary header), so test frames pass through the
# codec unchanged. The dedicated v3-frame test below negotiates version 3.
_HELLO = {
    "type": "hello",
    "version": 0,
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}


def _connect(client: TestClient):  # type: ignore[no-untyped-def]
    return client.websocket_connect("/api/bot/cores3-001/audio")


def test_hello_handshake(audio_ws_client_factory: Callable[..., TestClient]) -> None:
    client = audio_ws_client_factory(gateway=_FakeAgent())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        reply = ws.receive_json()
    assert reply["type"] == "hello"
    assert reply["transport"] == "websocket"
    assert reply["session_id"]
    assert reply["audio_params"]["sample_rate"] == 24000
    assert reply["audio_params"]["frame_duration"] == 60


def test_listen_to_stt_llm_tts_stream(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    asr = _FakeAsr(text="げんき？")
    decoder = _FakeDecoder()
    agent = _FakeAgent(AgentReply(text="元気だよ", emotion="happy"))
    client = audio_ws_client_factory(
        gateway=agent,
        speech_recognizer=asr,
        audio_decoder=decoder,
        speech_synthesizer=_SilentSynth(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()  # server hello
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_bytes(b"\x11" * 320)
        ws.send_json({"type": "listen", "state": "stop"})

        stt = ws.receive_json()
        llm = ws.receive_json()
        tts_start = ws.receive_json()
        tts_sentence = ws.receive_json()
        tts_stop = ws.receive_json()

    assert stt == {"type": "stt", "text": "げんき？"}
    assert llm == {"type": "llm", "emotion": "happy"}
    assert tts_start == {"type": "tts", "state": "start"}
    assert tts_sentence == {"type": "tts", "state": "sentence_start", "text": "元気だよ"}
    assert tts_stop == {"type": "tts", "state": "stop"}
    assert len(decoder.frames) == 2
    assert asr.received == [b"\x00" * 320 + b"\x11" * 320]
    assert agent.messages == ["げんき？"]


def test_frames_before_listen_start_are_ignored(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    asr = _FakeAsr()
    decoder = _FakeDecoder()
    client = audio_ws_client_factory(
        gateway=_FakeAgent(), speech_recognizer=asr, audio_decoder=decoder
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_bytes(b"\x00" * 320)  # no listen.start yet -> ignored
        ws.send_json({"type": "listen", "state": "start"})
        ws.send_bytes(b"\x01" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        ws.receive_json()  # stt
    assert decoder.frames == [b"\x01" * 320]


def test_listen_detect_starts_turn_from_text(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    agent = _FakeAgent(AgentReply(text="呼んだ？", emotion="curious"))
    client = audio_ws_client_factory(gateway=agent, speech_synthesizer=_SilentSynth())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "スタックチャン"})
        stt = ws.receive_json()
        llm = ws.receive_json()
    assert stt == {"type": "stt", "text": "スタックチャン"}
    assert llm == {"type": "llm", "emotion": "curious"}
    assert agent.messages == ["スタックチャン"]


def test_abort_emits_tts_stop_and_discards_turn(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    asr = _FakeAsr()
    client = audio_ws_client_factory(gateway=_FakeAgent(), speech_recognizer=asr)
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "abort", "reason": "wake_word_detected"})
        stop = ws.receive_json()
        # After abort, a stray frame and stop produce no further turn output.
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        # Connection still usable: a fresh hello-less listen.detect works.
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        stt = ws.receive_json()
    assert stop == {"type": "tts", "state": "stop"}
    assert stt == {"type": "stt", "text": "ねえ"}
    assert asr.received == []  # the aborted turn never reached ASR


def test_corrupt_frame_keeps_connection_alive(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    asr = _FakeAsr(text="平気")
    client = audio_ws_client_factory(
        gateway=_FakeAgent(), speech_recognizer=asr, audio_decoder=_ExplodingDecoder()
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start"})
        ws.send_bytes(b"\xff" * 8)  # decoder raises -> frame skipped
        ws.send_json({"type": "listen", "state": "stop"})
        stt = ws.receive_json()  # empty PCM still recognized by fake ASR
    assert stt == {"type": "stt", "text": "平気"}


def test_asr_failure_emits_tts_stop_without_breaking(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    client = audio_ws_client_factory(gateway=_FakeAgent(), speech_recognizer=_FailingAsr())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        msg = ws.receive_json()
    assert msg == {"type": "tts", "state": "stop"}


def test_agent_failure_emits_tts_stop(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    client = audio_ws_client_factory(gateway=_RaisingAgent(), speech_recognizer=_FakeAsr())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "やあ"})
        stt = ws.receive_json()
        stop = ws.receive_json()
    assert stt == {"type": "stt", "text": "やあ"}
    assert stop == {"type": "tts", "state": "stop"}


def test_mcp_payload_echoed(audio_ws_client_factory: Callable[..., TestClient]) -> None:
    client = audio_ws_client_factory(gateway=_FakeAgent())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": 1}})
        mcp = ws.receive_json()
    assert mcp["type"] == "mcp"
    assert mcp["payload"] == {"jsonrpc": "2.0", "id": 1}


def test_binary_version3_frame_is_unwrapped(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    import struct

    asr = _FakeAsr()
    decoder = _FakeDecoder()
    client = audio_ws_client_factory(
        gateway=_FakeAgent(), speech_recognizer=asr, audio_decoder=decoder
    )
    payload = b"opusdata"
    frame = struct.pack("!BBH", 0, 0, len(payload)) + payload
    with _connect(client) as ws:
        ws.send_json({**_HELLO, "version": 3})
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start"})
        ws.send_bytes(frame)
        ws.send_json({"type": "listen", "state": "stop"})
        ws.receive_json()  # stt
    assert decoder.frames == [payload]
