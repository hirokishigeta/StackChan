"""Domain model immutability and pure-logic tests."""

from __future__ import annotations

import dataclasses

import pytest
from app.domain.bot.entities import Bot
from app.domain.bot.value_objects import ConnectionStatus
from app.domain.settings.entities import BotSettings
from app.domain.wakeword.entities import WakeWordConfig
from app.domain.wakeword.services import resolve_active_wake_words
from app.domain.wakeword.value_objects import WakeWordEntry


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
    # New devices get a sensible default wake-word list the user can edit.
    assert len(settings.wake_word.wake_words) >= 1
    assert all(w.phrase.strip() for w in settings.wake_word.wake_words)


def test_wake_word_entry_rejects_empty_phrase() -> None:
    with pytest.raises(ValueError, match="phrase must not be empty"):
        WakeWordEntry(id="ww-x", phrase="   ")


def test_wake_word_entry_rejects_threshold_out_of_range() -> None:
    with pytest.raises(ValueError, match="threshold must be within"):
        WakeWordEntry(id="ww-x", phrase="hello", threshold=1.5)


def test_resolve_active_wake_words_returns_all_enabled() -> None:
    words = tuple(WakeWordEntry(id=f"ww-{i}", phrase=f"word {i}", enabled=True) for i in range(5))
    config = WakeWordConfig(wake_words=words)
    assert len(resolve_active_wake_words(config)) == 5


def test_resolve_active_wake_words_excludes_disabled() -> None:
    words = (
        WakeWordEntry(id="ww-1", phrase="a", enabled=True),
        WakeWordEntry(id="ww-2", phrase="b", enabled=False),
    )
    config = WakeWordConfig(wake_words=words)
    active = resolve_active_wake_words(config)
    assert [w.id for w in active] == ["ww-1"]
