"""Unit tests for the pure backend wake-word matcher (ADR-0014).

``matches_wake_word`` decides whether a recognized (STT) transcript contains a
configured wake phrase. It is the only business logic behind the WS wake gate,
so it is tested directly with no I/O.
"""

from __future__ import annotations

from app.domain.wakeword.value_objects import canonicalize_wake_word, matches_wake_word


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


# -- canonicalize_wake_word (ADR-0017) --------------------------------------

_WORDS = ["ベルちゃん", "レルちゃん", "エルちゃん"]
_CANON = "ベルちゃん"


def test_canonicalize_rewrites_mistranscribed_variant() -> None:
    assert (
        canonicalize_wake_word("レルちゃん、こんにちは", _WORDS, _CANON) == "ベルちゃん、こんにちは"
    )


def test_canonicalize_leaves_canonical_unchanged() -> None:
    assert canonicalize_wake_word("ベルちゃん、おはよう", _WORDS, _CANON) == "ベルちゃん、おはよう"


def test_canonicalize_no_match_returns_text_unchanged() -> None:
    assert canonicalize_wake_word("今日はいい天気だね", _WORDS, _CANON) == "今日はいい天気だね"


def test_canonicalize_replaces_phrase_mid_sentence() -> None:
    assert (
        canonicalize_wake_word("ねえ、エルちゃんって元気？", _WORDS, _CANON)
        == "ねえ、ベルちゃんって元気？"
    )


def test_canonicalize_prefers_longest_phrase() -> None:
    # "ねえスタックチャン" must win over the shorter "スタックチャン" so the
    # whole greeting collapses to the canonical, not just the tail.
    words = ["スタックチャン", "ねえスタックチャン"]
    assert canonicalize_wake_word("ねえスタックチャン！", words, "ベルちゃん") == "ベルちゃん！"


def test_canonicalize_blank_canonical_is_noop() -> None:
    assert canonicalize_wake_word("レルちゃん", _WORDS, "") == "レルちゃん"
