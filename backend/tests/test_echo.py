"""Tests for echo detection (drop the bot's own reply captured by the mic)."""

from __future__ import annotations

from app.domain.speech.echo import is_echo_of

_REPLY = "今日はとても良い天気ですね。お散歩でもいかがでしょうか。"


def test_exact_reply_is_echo() -> None:
    assert is_echo_of("今日はとても良い天気ですね", _REPLY) is True


def test_fragment_of_reply_is_echo() -> None:
    assert is_echo_of("お散歩でもいかがでしょうか", _REPLY) is True


def test_slightly_misheard_echo_still_matches() -> None:
    # One character off (ASR mis-transcription of the echo).
    assert is_echo_of("今日はとても良い天気ですわ", _REPLY) is True


def test_different_user_utterance_is_not_echo() -> None:
    assert is_echo_of("おなかすいたけど何食べたらいい", _REPLY) is False


def test_short_utterance_never_echo() -> None:
    # Short answers like these can legitimately appear inside a reply; never drop.
    assert is_echo_of("うん", _REPLY) is False
    assert is_echo_of("はい", "はい、承知しました") is False


def test_empty_inputs() -> None:
    assert is_echo_of("", _REPLY) is False
    assert is_echo_of("今日はとても良い天気", "") is False
