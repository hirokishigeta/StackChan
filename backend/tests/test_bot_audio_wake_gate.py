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
from app.domain.wakeword.entities import WakeWordConfig
from app.domain.wakeword.value_objects import WakeWordEntry
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
        assert ws.receive_json() == {"type": "llm", "emotion": "happy"}
        assert ws.receive_json() == {"type": "tts", "state": "start"}
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
        for expected in ("stt", "llm", "tts", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
        # Second utterance has no wake word but should be processed (engaged).
        asr.text = "それで、続きの話なんだけど"
        ws.send_bytes(b"\x00" * 320)
        ws.send_json({"type": "listen", "state": "stop"})
        assert ws.receive_json() == {"type": "stt", "text": "それで、続きの話なんだけど"}
        for expected in ("llm", "tts", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    assert agent.messages == ["スタックチャン おはよう", "それで、続きの話なんだけど"]


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
        for expected in ("llm", "tts", "tts", "tts"):
            assert ws.receive_json()["type"] == expected
    assert agent.messages == ["ただのひとりごと"]
