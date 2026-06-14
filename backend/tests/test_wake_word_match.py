"""Unit tests for the pure backend wake-word matcher (ADR-0014).

``matches_wake_word`` decides whether a recognized (STT) transcript contains a
configured wake phrase. It is the only business logic behind the WS wake gate,
so it is tested directly with no I/O.
"""

from __future__ import annotations

from app.domain.wakeword.value_objects import matches_wake_word


def test_matches_japanese_phrase_as_substring() -> None:
    assert matches_wake_word("ねえスタックチャン、おはよう", ["スタックチャン"])


def test_matches_ignoring_surrounding_whitespace_and_punctuation() -> None:
    # Punctuation/whitespace inside the transcript are stripped before matching.
    assert matches_wake_word("ねえ、スタック チャン！ 元気？", ["スタックチャン"])


def test_matches_is_case_insensitive_for_latin() -> None:
    assert matches_wake_word("Hey StackChan!", ["stackchan"])


def test_matches_full_width_and_half_width_equivalent() -> None:
    # NFKC folds full-width ASCII to half-width.
    assert matches_wake_word("ｈｅｙ ロボ", ["hey ロボ"])


def test_no_match_when_phrase_absent() -> None:
    assert not matches_wake_word("今日はいい天気だね", ["スタックチャン"])


def test_no_match_for_empty_phrase_list() -> None:
    assert not matches_wake_word("スタックチャン", [])


def test_blank_phrase_never_matches() -> None:
    assert not matches_wake_word("なんでもいい", ["   "])


def test_empty_text_never_matches() -> None:
    assert not matches_wake_word("", ["スタックチャン"])


def test_matches_any_of_multiple_phrases() -> None:
    assert matches_wake_word("おーい ロボ", ["スタックチャン", "ロボ"])
