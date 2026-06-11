"""Domain model immutability and pure-logic tests."""

from __future__ import annotations

import dataclasses

import pytest
from app.domain.bot.entities import Bot
from app.domain.bot.value_objects import ConnectionStatus
from app.domain.settings.entities import BotSettings
from app.domain.wakeword.entities import WakeWordConfig
from app.domain.wakeword.services import resolve_active_wake_words
from app.domain.wakeword.value_objects import DetectionMethod, WakeWordEntry


def test_bot_is_frozen() -> None:
    bot = Bot(device_id="cores3-001", name="bot", firmware_version="0.1.0")
    with pytest.raises(dataclasses.FrozenInstanceError):
        bot.name = "changed"  # type: ignore[misc]


def test_bot_with_connection_status_returns_new_instance() -> None:
    bot = Bot(device_id="cores3-001", name="bot", firmware_version="0.1.0")
    connected = bot.with_connection_status(ConnectionStatus.CONNECTED)
    assert bot.connection_status is ConnectionStatus.DISCONNECTED
    assert connected.connection_status is ConnectionStatus.CONNECTED
    assert connected is not bot


def test_default_settings_have_expected_device_id() -> None:
    settings = BotSettings.default("cores3-001")
    assert settings.device_id == "cores3-001"
    assert settings.wake_word.wake_words == ()


def test_resolve_active_wake_words_caps_local_detection() -> None:
    words = tuple(WakeWordEntry(id=f"ww-{i}", phrase=f"word {i}", enabled=True) for i in range(5))
    config = WakeWordConfig(
        detection_method=DetectionMethod.LOCAL,
        max_local_active=3,
        wake_words=words,
    )
    assert len(resolve_active_wake_words(config)) == 3


def test_resolve_active_wake_words_backend_uncapped() -> None:
    words = tuple(WakeWordEntry(id=f"ww-{i}", phrase=f"word {i}", enabled=True) for i in range(5))
    config = WakeWordConfig(
        detection_method=DetectionMethod.BACKEND,
        max_local_active=3,
        wake_words=words,
    )
    assert len(resolve_active_wake_words(config)) == 5


def test_resolve_active_wake_words_excludes_disabled() -> None:
    words = (
        WakeWordEntry(id="ww-1", phrase="a", enabled=True),
        WakeWordEntry(id="ww-2", phrase="b", enabled=False),
    )
    config = WakeWordConfig(detection_method=DetectionMethod.LOCAL, wake_words=words)
    active = resolve_active_wake_words(config)
    assert [w.id for w in active] == ["ww-1"]
