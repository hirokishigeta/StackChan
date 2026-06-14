"""Backend wake-word gate WS tests (ADR-0014).

With ``wake_word_gate_enabled`` the device streams continuously and the backend
decides when to engage: an utterance reaches the agent only if it contains a
configured wake word (or the session is already engaged within the idle
window). Exercised end-to-end over the WS endpoint with fakes (no models / no
network, CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable

from app.di_container import container as container_module
from app.domain.settings.entities import BotSettings
from app.domain.wakeword.entities import EndWordConfig, WakeWordConfig
from app.domain.wakeword.value_objects import EndWordEntry, WakeWordEntry
from fastapi.testclient import TestClient

from tests.test_bot_audio_ws import (
    _HELLO,
    _connect,
    _FakeAgent,
    _FakeAsr,
    _FakeDecoder,
    _SilentSynth,
)

_DEVICE = "cores3-001"


def _seed_wake_words(*phrases: str) -> None:
    """Store a device settings aggregate with the given enabled wake words.

    Uses the live container's repository (bound during the TestClient context),
    mirroring how a dashboard PUT would persist per-device settings.
    """
    repo = container_module.get_container().repository
    entries = tuple(WakeWordEntry(id=f"ww-{i}", phrase=p) for i, p in enumerate(phrases))
    repo.save_settings(BotSettings(device_id=_DEVICE, wake_word=WakeWordConfig(wake_words=entries)))


def _seed_wake_and_end_words(wake: tuple[str, ...], end: tuple[str, ...]) -> None:
    """Store device settings with the given enabled wake words and end words."""
    repo = container_module.get_container().repository
    wake_entries = tuple(WakeWordEntry(id=f"ww-{i}", phrase=p) for i, p in enumerate(wake))
    end_entries = tuple(EndWordEntry(id=f"ew-{i}", phrase=p) for i, p in enumerate(end))
    repo.save_settings(
        BotSettings(
            device_id=_DEVICE,
            wake_word=WakeWordConfig(wake_words=wake_entries),
            end_word=EndWordConfig(end_words=end_entries),
        )
    )


def _gate_client(
    factory: Callable[..., TestClient],
    *,
    agent: _FakeAgent,
    asr: _FakeAsr,
) -> TestClient:
    return factory(
        gateway=agent,
        speech_recognizer=asr,
        audio_decoder=_FakeDecoder(),
        speech_synthesizer=_SilentSynth(),
        settings_overrides={"wake_word_gate_enabled": True},
    )


def test_gate_ignores_utterance_without_wake_word(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """Gate on + non-wake utterance -> agent NOT called, tts stop, alive."""
    asr = _FakeAsr(text="今日はいい天気だね")
    agent = _FakeAgent()
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    _seed_wake_words("スタックチャン")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        # Ambient speech is ignored: only a tts.stop returns the device to idle.
        assert ws.receive_json() == {"type": "tts", "state": "stop"}
        # Connection still usable.
        ws.send_json({"type": "mcp", "payload": {"id": 1}})
        assert ws.receive_json()["type"] == "mcp"
    assert agent.messages == []  # agent never engaged
    assert len(asr.received) == 1  # ASR ran; the gate dropped the result


def test_gate_engages_on_wake_word_and_runs_full_flow(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """Gate on + transcript containing a wake word -> agent called, reply flows."""
    asr = _FakeAsr(text="ねえスタックチャン、元気？")
    agent = _FakeAgent()  # default reply text="やあ" emotion="happy"
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    _seed_wake_words("スタックチャン")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "ねえスタックチャン、元気？"}
        # tts.start opens the speaking window before the agent call (so tool
        # progress can be surfaced), then the engagement signal + emotion.
        assert ws.receive_json() == {"type": "tts", "state": "start"}
        assert ws.receive_json() == {"type": "wake", "state": "engaged"}
        assert ws.receive_json() == {"type": "llm", "emotion": "happy"}
        assert ws.receive_json()["state"] == "sentence_start"
        assert ws.receive_json() == {"type": "tts", "state": "stop"}
    assert agent.messages == ["ねえスタックチャン、元気？"]  # full utterance kept


def test_once_engaged_following_non_wake_utterance_is_processed(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """After engaging, a follow-up without the wake word still runs (within idle)."""
    asr = _FakeAsr(text="スタックチャン おはよう")
    agent = _FakeAgent()
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    _seed_wake_words("スタックチャン")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        # First utterance engages.
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        # First turn also emits the engagement signal ("wake") right after stt.
        for expected in ("stt", "tts", "wake", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        # Second utterance has no wake word but should be processed (engaged).
        asr.text = "それで、続きの話なんだけど"
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "それで、続きの話なんだけど"}
        for expected in ("tts", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    assert agent.messages == ["スタックチャン おはよう", "それで、続きの話なんだけど"]


def test_engaged_session_ends_on_per_device_end_word(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """An engaged session ends on a DEVICE-configured end word (ADR-0016).

    The end word here ("もうおしまい") is NOT in the global default
    ``conversation_end_words`` list, so ending on it proves the per-device list
    is what drives the gate. Ending -> the device is returned to wake-waiting
    (``{"type":"wake","state":"waiting"}``), not stopped.
    """
    asr = _FakeAsr(text="ねえスタックチャン")
    agent = _FakeAgent()
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    _seed_wake_and_end_words(wake=("スタックチャン",), end=("もうおしまい",))
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        # First utterance engages.
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        for expected in ("stt", "tts", "wake", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        # Second utterance contains the per-device end word -> conversation ends.
        asr.text = "ありがとう、もうおしまい"
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "ありがとう、もうおしまい"}
        for expected in ("tts", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        # Ending returns the device to wake-waiting (not a listen stop).
        assert ws.receive_json() == {"type": "wake", "state": "waiting"}
    # Both utterances reached the agent; the end word is still a real turn.
    assert agent.messages == ["ねえスタックチャン", "ありがとう、もうおしまい"]


def test_engaged_session_falls_back_to_global_end_words(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """With no device end words, the global AppSettings list ends the talk."""
    asr = _FakeAsr(text="ねえスタックチャン")
    agent = _FakeAgent()
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    # Wake words only -> device.end_word.end_words is empty -> global fallback.
    _seed_wake_and_end_words(wake=("スタックチャン",), end=())
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        for expected in ("stt", "tts", "wake", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        # "ばいばい" is in the default global conversation_end_words list.
        asr.text = "じゃあね、ばいばい"
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "じゃあね、ばいばい"}
        for expected in ("tts", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        assert ws.receive_json() == {"type": "wake", "state": "waiting"}


def test_gate_corrects_mistranscribed_wake_word_for_agent(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """A mis-transcribed wake variant is rewritten to the canonical name (ADR-0017).

    The device's wake list has the canonical "ベルちゃん" first plus the common
    STT mishearing "レルちゃん". ASR returns the garbled variant, the gate still
    matches, and the wake phrase is rewritten to the canonical name before the
    turn is handed to the agent.
    """
    asr = _FakeAsr(text="レルちゃん、こんにちは")
    agent = _FakeAgent()
    client = _gate_client(audio_ws_client_factory, agent=agent, asr=asr)
    _seed_wake_words("ベルちゃん", "レルちゃん")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        # The corrected text is what flows downstream (stt + agent).
        assert ws.receive_json() == {"type": "stt", "text": "ベルちゃん、こんにちは"}
        for expected in ("tts", "wake", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    # The agent sees the corrected canonical name.
    assert agent.messages == ["ベルちゃん、こんにちは"]


def test_gate_engages_on_fuzzy_mistranscription_and_corrects(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """A fuzzy (edit-distance) mis-transcription engages and is canonicalized (ADR-0018).

    Only the canonical "ベルちゃん" is configured (no enumerated variant). The
    ASR returns the garble "ねるちゃん" (Levenshtein distance 1). With
    ``wake_fuzzy_max_dist`` > 0 the gate still engages, and the fuzzy span is
    rewritten to the canonical name before the agent sees it.
    """
    asr = _FakeAsr(text="ねるちゃん、こんにちは")
    agent = _FakeAgent()
    client = audio_ws_client_factory(
        gateway=agent,
        speech_recognizer=asr,
        audio_decoder=_FakeDecoder(),
        speech_synthesizer=_SilentSynth(),
        settings_overrides={"wake_word_gate_enabled": True, "wake_fuzzy_max_dist": 2},
    )
    _seed_wake_words("ベルちゃん")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        # Corrected canonical text flows downstream (stt + agent).
        assert ws.receive_json() == {"type": "stt", "text": "ベルちゃん、こんにちは"}
        for expected in ("tts", "wake", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    assert agent.messages == ["ベルちゃん、こんにちは"]


def test_gate_ignores_fuzzy_match_when_disabled(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """With ``wake_fuzzy_max_dist=0`` a garble does NOT engage (exact-only)."""
    asr = _FakeAsr(text="ねるちゃん、こんにちは")
    agent = _FakeAgent()
    client = audio_ws_client_factory(
        gateway=agent,
        speech_recognizer=asr,
        audio_decoder=_FakeDecoder(),
        speech_synthesizer=_SilentSynth(),
        settings_overrides={"wake_word_gate_enabled": True, "wake_fuzzy_max_dist": 0},
    )
    _seed_wake_words("ベルちゃん")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "tts", "state": "stop"}
    assert agent.messages == []


def test_gate_disabled_processes_everything(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    """Default (gate off): a non-wake utterance is processed exactly as today."""
    asr = _FakeAsr(text="ただのひとりごと")
    agent = _FakeAgent()
    client = audio_ws_client_factory(
        gateway=agent,
        speech_recognizer=asr,
        audio_decoder=_FakeDecoder(),
        speech_synthesizer=_SilentSynth(),
    )
    _seed_wake_words("スタックチャン")
    with _connect(client) as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
        ws.send_json({"type": "listen", "state": "start", "mode": "manual"})
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "ただのひとりごと"}
        for expected in ("tts", "llm", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    assert agent.messages == ["ただのひとりごと"]
