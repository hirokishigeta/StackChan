"""Downlink TTS audio tests (Issue #7-b).

Exercises the ``tts.start`` -> binary audio frames -> ``tts.stop`` downlink flow
with fakes (fake SpeechSynthesizer / AudioEncoder / AgentGateway) — no heavy
deps, no models, no native codec (CLAUDE.md). Verifies:

- the full message stream (stt/llm/tts.start/sentence_start/<audio>/tts.stop),
- emotion -> Irodori emoji style mapping,
- TTS-disabled (failing synth) degrades to text-only without breaking the conn,
- the resampler and frame splitting behave as expected.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

from app.application.ports.agent_gateway import AgentGateway, ProgressCallback
from app.application.ports.audio_encoder import AudioEncodeError, AudioEncoder
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.application.ports.speech_synthesizer import SpeechSynthesisError, SpeechSynthesizer
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply, ProactiveEvent
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import AudioFormat, SpeechRecognitionResult, SynthesizedAudio
from app.infrastructure.audio.raw_pcm_audio_encoder import RawPcmAudioEncoder
from app.infrastructure.audio.resample import resample_pcm16
from app.infrastructure.tts.dummy_speech_synthesizer import DummySpeechSynthesizer
from app.infrastructure.tts.emotion_style import style_text
from fastapi.testclient import TestClient


class _FakeAgent(AgentGateway):
    def __init__(self, reply: AgentReply) -> None:
        self.reply = reply

    async def chat(
        self,
        *,
        message: str,
        profile: AgentProfile,
        context: dict[str, object] | None = None,
        progress_cb: ProgressCallback | None = None,
    ) -> AgentReply:
        return self.reply

    async def proactive(self, *, event: ProactiveEvent, profile: AgentProfile) -> AgentReply:
        return self.reply


class _FakeAsr(SpeechRecognizer):
    async def recognize(
        self, *, audio: bytes, config: SpeechRecognitionConfig
    ) -> SpeechRecognitionResult:
        return SpeechRecognitionResult(text="やあ", language=config.language, confidence=1.0)


class _RecordingSynth(SpeechSynthesizer):
    """Records (text, emotion) and returns a fixed PCM at 48 kHz (Irodori-like)."""

    def __init__(self, *, sample_count: int = 4800, sample_rate: int = 48000) -> None:
        self.calls: list[tuple[str, str]] = []
        self._pcm = b"\x01\x02" * sample_count
        self._sample_rate = sample_rate

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        self.calls.append((text, emotion))
        return SynthesizedAudio(pcm=self._pcm, sample_rate=self._sample_rate)


class _StyleRecordingSynth(SpeechSynthesizer):
    """Applies the emoji style mapping so the wire text can be asserted."""

    def __init__(self) -> None:
        self.styled: list[str] = []

    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        self.styled.append(style_text(text=text, emotion=emotion))
        return SynthesizedAudio(pcm=b"\x00\x00" * 1440, sample_rate=24000)


class _FailingSynth(SpeechSynthesizer):
    def synthesize(self, *, text: str, emotion: str = "neutral") -> SynthesizedAudio:
        raise SpeechSynthesisError("no model")


class _FailingEncoder(AudioEncoder):
    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        raise AudioEncodeError("no codec")


_HELLO = {
    "type": "hello",
    "version": 0,
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}


def _connect(client: TestClient):  # type: ignore[no-untyped-def]
    return client.websocket_connect("/api/bot/cores3-001/audio")


def _drain_to_stop(ws):  # type: ignore[no-untyped-def]
    """Receive messages after sentence_start until tts.stop, collecting frames."""
    audio_frames: list[bytes] = []
    while True:
        message = ws.receive()
        if message.get("bytes") is not None:
            audio_frames.append(message["bytes"])
            continue
        import json

        data = json.loads(message["text"])
        if data == {"type": "tts", "state": "stop"}:
            return audio_frames


def test_tts_audio_frames_between_start_and_stop(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    synth = _RecordingSynth(sample_count=4800, sample_rate=48000)  # 0.1 s @ 48k
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="げんき", emotion="happy")),
        speech_synthesizer=synth,
        audio_encoder=RawPcmAudioEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()  # server hello
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        assert ws.receive_json() == {"type": "stt", "text": "ねえ"}
        assert ws.receive_json() == {"type": "tts", "state": "start"}
        assert ws.receive_json() == {"type": "llm", "emotion": "happy"}
        assert ws.receive_json() == {"type": "tts", "state": "sentence_start", "text": "げんき"}
        frames = _drain_to_stop(ws)

    assert synth.calls == [("げんき", "happy")]
    # 0.1 s @ 48k -> 24k = 2400 samples = 4800 bytes; 60 ms frame @ 24k = 2880
    # bytes -> 2 frames (2880 + 1920).
    assert len(frames) == 2
    assert sum(len(f) for f in frames) == 4800


def test_end_conversation_sends_listen_stop(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    # When the agent judges the conversation over, after tts.stop the server
    # tells the device to stop listening (so it returns to idle, not auto-relisten).
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="またね", emotion="happy", end_conversation=True)),
        speech_synthesizer=_RecordingSynth(sample_count=480, sample_rate=48000),
        audio_encoder=RawPcmAudioEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ばいばい"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        _drain_to_stop(ws)
        # After tts.stop, a server-initiated listen stop closes the turn loop.
        assert ws.receive_json() == {"type": "listen", "state": "stop"}


def test_no_listen_stop_when_conversation_continues(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    # The common case: conversation continues -> no listen stop after tts.stop.
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="うん", emotion="happy")),
        speech_synthesizer=_RecordingSynth(sample_count=480, sample_rate=48000),
        audio_encoder=RawPcmAudioEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "やあ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        frames = _drain_to_stop(ws)
        # Continue the conversation; the next message must be stt, not listen stop.
        ws.send_json({"type": "listen", "state": "detect", "text": "もう一回"})
        assert ws.receive_json() == {"type": "stt", "text": "もう一回"}
    assert frames is not None


def test_downlink_lead_silence_prepended(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    # The CoreS3 drops a fixed window at playback start; a lead-in of silence
    # absorbs it so the opening syllable survives. The stream must start with
    # >= the configured silence as all-zero PCM (RawPcm encoder = passthrough).
    synth = _RecordingSynth(sample_count=4800, sample_rate=48000)  # 0.1 s @ 48k
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="げんき", emotion="happy")),
        speech_synthesizer=synth,
        audio_encoder=RawPcmAudioEncoder(),
        settings_overrides={"downlink_lead_silence_ms": 300},
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        frames = _drain_to_stop(ws)
    stream = b"".join(frames)
    lead_bytes = (24000 * 300 // 1000) * 1 * 2  # 300 ms @ 24 kHz mono PCM16
    assert len(stream) >= lead_bytes + 4800
    assert stream[:lead_bytes] == b"\x00" * lead_bytes


def test_emotion_maps_to_irodori_emoji_style(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    synth = _StyleRecordingSynth()
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="おはよう", emotion="sleepy")),
        speech_synthesizer=synth,
        audio_encoder=RawPcmAudioEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        _drain_to_stop(ws)
    # No constant base by default; sleepy emoji (😪) appended to the text.
    assert synth.styled == ["おはよう😪"]


def test_full_emotion_emoji_table() -> None:
    # Voice character comes from the VoiceDesign caption; per-emotion emoji are
    # appended (no constant base by default). angry is restrained (no extra
    # emoji). Unknown -> neutral fallback.
    assert style_text(text="x", emotion="neutral") == "x⏸️"
    assert style_text(text="x", emotion="happy") == "x🤭"
    assert style_text(text="x", emotion="sad") == "x😮‍💨😪"
    assert style_text(text="x", emotion="angry") == "x"
    assert style_text(text="x", emotion="curious") == "x⏸️🫣"
    assert style_text(text="x", emotion="surprised") == "x🫣"
    assert style_text(text="x", emotion="sleepy") == "x😪"
    assert style_text(text="x", emotion="shy") == "x🫣🫶👂"
    assert style_text(text="x", emotion="intimate") == "x🫣🫶👂"
    # Unknown emotion falls back to the neutral style.
    assert style_text(text="x", emotion="bogus") == "x⏸️"
    # Base style is overridable (e.g. a persona overlay can be re-enabled).
    assert style_text(text="x", emotion="happy", base_style="😏") == "😏x🤭"


def test_synth_failure_falls_back_to_text_only(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="よろしく", emotion="happy")),
        speech_synthesizer=_FailingSynth(),
        audio_encoder=RawPcmAudioEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        sentence = ws.receive_json()
        stop = ws.receive_json()  # no audio frames -> stop comes right after
    assert sentence == {"type": "tts", "state": "sentence_start", "text": "よろしく"}
    assert stop == {"type": "tts", "state": "stop"}


def test_encoder_failure_falls_back_to_text_only(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="またね", emotion="sad")),
        speech_synthesizer=_RecordingSynth(),
        audio_encoder=_FailingEncoder(),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        stop = ws.receive_json()
        # Connection still usable after the fallback.
        ws.send_json({"type": "listen", "state": "detect", "text": "もう一度"})
        again = ws.receive_json()
    assert stop == {"type": "tts", "state": "stop"}
    assert again == {"type": "stt", "text": "もう一度"}


def test_default_dummy_synth_produces_frames(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    # No synthesizer/encoder injected -> registry defaults (dummy synth + raw
    # encoder) wire up and produce real downlink frames without heavy deps.
    client = audio_ws_client_factory(
        gateway=_FakeAgent(AgentReply(text="やっほー", emotion="happy")),
    )
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "detect", "text": "ねえ"})
        ws.receive_json()  # stt
        ws.receive_json()  # llm
        ws.receive_json()  # tts.start
        ws.receive_json()  # sentence_start
        frames = _drain_to_stop(ws)
    assert frames  # at least one downlink audio frame


def test_half_duplex_drops_uplink_audio_while_speaking() -> None:
    # No device AEC: while the bot is speaking, uplink frames must be dropped so
    # the bot's own TTS voice never reaches the decoder/VAD (echo loop).
    import anyio
    from app.application.ports.audio_decoder import AudioDecoder
    from app.config.settings import AppSettings
    from app.interfaces.api.bot_audio_ws import BotAudioHandler, _Session

    class _RecordingDecoder(AudioDecoder):
        def __init__(self) -> None:
            self.calls = 0

        def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
            self.calls += 1
            return b"\x10\x00" * 320

    decoder = _RecordingDecoder()
    handler = BotAudioHandler(
        settings=AppSettings(),
        speech_recognizer=_FakeAsr(),
        agent_gateway=_FakeAgent(AgentReply(text="x", emotion="neutral")),
        audio_decoder=decoder,
        speech_synthesizer=_RecordingSynth(),
        audio_encoder=RawPcmAudioEncoder(),
        repository=object(),  # type: ignore[arg-type]  # unused on this path
    )
    session = _Session(device_id="d", session_id="s", listening=True, listen_mode="auto")
    frame = b"\x01\x00" * 320  # version 0 == raw PCM payload

    session.speaking = True
    anyio.run(handler._on_binary, None, session, frame)  # type: ignore[arg-type]
    assert decoder.calls == 0  # gated: nothing decoded or buffered
    assert len(session.pcm_buffer) == 0

    session.speaking = False
    anyio.run(handler._on_binary, None, session, frame)  # type: ignore[arg-type]
    assert decoder.calls == 1  # mic re-opened: frame is decoded and buffered
    assert len(session.pcm_buffer) > 0


def test_irodori_warm_up_preloads_and_swallows_errors() -> None:
    # warm_up must preload the runtime and never raise (port contract): a
    # missing model path raises SpeechSynthesisError internally, swallowed here.
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    loaded = {"n": 0}

    class _Synth(IrodoriTtsSynthesizer):
        def _load_runtime(self) -> object:
            loaded["n"] += 1
            return object()

    _Synth(AppSettings()).warm_up()
    assert loaded["n"] == 1

    # With no deps/model path the real load raises; warm_up must not propagate.
    IrodoriTtsSynthesizer(AppSettings()).warm_up()  # no exception


def test_default_synth_warm_up_is_noop() -> None:
    from app.config.settings import AppSettings

    DummySpeechSynthesizer(AppSettings()).warm_up()  # no-op, no exception


def test_resample_48k_to_24k_halves_sample_count() -> None:
    pcm = b"\x01\x02" * 480  # 480 samples @ 48k
    out = resample_pcm16(pcm=pcm, src_rate=48000, dst_rate=24000)
    assert len(out) // 2 == 240


def test_resample_noop_when_rates_match() -> None:
    pcm = b"\x01\x02" * 100
    assert resample_pcm16(pcm=pcm, src_rate=24000, dst_rate=24000) == pcm


def test_dummy_synth_scales_with_text() -> None:
    from app.config.settings import AppSettings

    synth = DummySpeechSynthesizer(AppSettings())
    short = synth.synthesize(text="あ")
    long = synth.synthesize(text="あ" * 50)
    assert short.sample_rate == 24000
    assert len(long.pcm) > len(short.pcm)


def test_irodori_synth_raises_without_optional_deps_or_model() -> None:
    # With neither torch/irodori_tts installed nor a model path, synthesize must
    # raise SpeechSynthesisError (lazy, never crashing at import) so the WS loop
    # degrades to text-only. This must hold in the make-check env (no heavy deps).
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    synth = IrodoriTtsSynthesizer(AppSettings())  # construction stays lazy
    try:
        synth.synthesize(text="やあ", emotion="happy")
    except SpeechSynthesisError:
        return
    raise AssertionError("expected SpeechSynthesisError without deps/model")


def test_irodori_float_to_pcm16_clamps_and_flattens() -> None:
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    # Nested (channels, samples)-style float list, with out-of-range values.
    pcm = IrodoriTtsSynthesizer._float_to_pcm16([[0.0, 1.5, -2.0, -0.5]])
    assert len(pcm) == 4 * 2  # 4 samples -> PCM16
    samples = struct.unpack("<4h", pcm)
    assert samples[0] == 0
    assert samples[1] == 32767  # clamped from 1.5
    assert samples[2] == -32767  # clamped from -2.0
    assert samples[3] == round(-0.5 * 32767.0)


def test_irodori_synthesize_uses_runtime_and_no_ref_fallback() -> None:
    # Inject a fake runtime to exercise synthesize() without heavy deps: verify
    # styled text reaches SamplingRequest, no_ref=True when ref unset, and
    # result.audio/sample_rate are converted to SynthesizedAudio.
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    class _FakeRequest:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _FakeResult:
        audio = [[0.5, -0.5]]
        sample_rate = 48000

    captured: dict[str, object] = {}

    class _FakeRuntime:
        def synthesize(self, req: object) -> _FakeResult:
            captured["text"] = req.text  # type: ignore[attr-defined]
            captured["caption"] = req.caption  # type: ignore[attr-defined]
            captured["ref_wav"] = req.ref_wav  # type: ignore[attr-defined]
            captured["no_ref"] = req.no_ref  # type: ignore[attr-defined]
            return _FakeResult()

    caption = "明るく楽しそうな少女の声"
    synth = IrodoriTtsSynthesizer(AppSettings(irodori_model_path="x", irodori_caption=caption))
    synth._runtime = _FakeRuntime()  # pre-seed so _load_runtime short-circuits
    synth._request_cls = _FakeRequest
    out = synth.synthesize(text="げんき", emotion="happy")

    assert out.sample_rate == 48000
    assert len(out.pcm) == 2 * 2
    assert captured["text"] == "げんき🤭"  # no base by default + happy emoji
    assert captured["caption"] == caption  # VoiceDesign caption flows through
    assert captured["ref_wav"] is None
    assert captured["no_ref"] is True


def test_irodori_synthesize_passes_ref_wav_when_set() -> None:
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    class _FakeRequest:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _FakeResult:
        audio = [0.0]
        sample_rate = 48000

    captured: dict[str, object] = {}

    class _FakeRuntime:
        def synthesize(self, req: object) -> _FakeResult:
            captured["ref_wav"] = req.ref_wav  # type: ignore[attr-defined]
            captured["no_ref"] = req.no_ref  # type: ignore[attr-defined]
            return _FakeResult()

    synth = IrodoriTtsSynthesizer(
        AppSettings(irodori_model_path="x", irodori_reference_wav_path="/tmp/ref.wav")
    )
    synth._runtime = _FakeRuntime()
    synth._request_cls = _FakeRequest
    synth.synthesize(text="やあ", emotion="neutral")
    assert captured["ref_wav"] == "/tmp/ref.wav"
    assert captured["no_ref"] is False


def test_irodori_generate_reference_uses_no_ref_caption_and_steps() -> None:
    # generate_reference is the inverse of synthesize: no_ref=True with an
    # explicit caption and the higher generation step count, used to mint a
    # brand-new reference voice (ADR-0013).
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    class _FakeRequest:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _FakeResult:
        audio = [[0.25, -0.25]]
        sample_rate = 48000

    captured: dict[str, object] = {}

    class _FakeRuntime:
        def synthesize(self, req: object) -> _FakeResult:
            captured["text"] = req.text  # type: ignore[attr-defined]
            captured["caption"] = req.caption  # type: ignore[attr-defined]
            captured["ref_wav"] = req.ref_wav  # type: ignore[attr-defined]
            captured["no_ref"] = req.no_ref  # type: ignore[attr-defined]
            captured["num_steps"] = req.num_steps  # type: ignore[attr-defined]
            captured["seed"] = req.seed  # type: ignore[attr-defined]
            return _FakeResult()

    synth = IrodoriTtsSynthesizer(
        AppSettings(irodori_model_path="x", irodori_generation_num_steps=64, irodori_seed=7)
    )
    synth._runtime = _FakeRuntime()
    synth._request_cls = _FakeRequest
    out = synth.generate_reference(text="こんにちは", caption="明るい少女の声")

    assert out.sample_rate == 48000
    assert captured["text"] == "こんにちは"  # caption-driven, text passed verbatim
    assert captured["caption"] == "明るい少女の声"
    assert captured["ref_wav"] is None
    assert captured["no_ref"] is True
    assert captured["num_steps"] == 64
    assert captured["seed"] == 7  # default from settings when not overridden


def test_irodori_synthesize_normalizes_runtime_errors() -> None:
    from app.config.settings import AppSettings
    from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer

    class _FakeRequest:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _BoomRuntime:
        def synthesize(self, req: object) -> object:
            raise RuntimeError("cuda oom")

    synth = IrodoriTtsSynthesizer(AppSettings(irodori_model_path="x"))
    synth._runtime = _BoomRuntime()
    synth._request_cls = _FakeRequest
    try:
        synth.synthesize(text="やあ")
    except SpeechSynthesisError:
        return
    raise AssertionError("engine error must surface as SpeechSynthesisError")


def test_split_sentences_splits_on_japanese_and_latin_enders() -> None:
    from app.interfaces.api.bot_audio_ws import _split_sentences

    # Boundaries: 。．！？!? and newline. ASCII "." is intentionally NOT a
    # boundary (would mis-split decimals/abbreviations in mixed text).
    text = "こんにちは。元気？\nそれは良い！Yes. ok"
    assert _split_sentences(text) == ["こんにちは。", "元気？", "それは良い！", "Yes. ok"]


def test_split_sentences_keeps_single_sentence_intact() -> None:
    from app.interfaces.api.bot_audio_ws import _split_sentences

    # No boundary -> one chunk; trailing whitespace stripped.
    assert _split_sentences("元気だよ") == ["元気だよ"]
    assert _split_sentences("やっほー！") == ["やっほー！"]


def test_split_sentences_drops_empty_fragments() -> None:
    from app.interfaces.api.bot_audio_ws import _split_sentences

    assert _split_sentences("はい。。\n\n  そう。") == ["はい。", "。", "そう。"]
    assert _split_sentences("") == []
