"""Unit tests for the pure backend wake-word matcher (ADR-0014).

``matches_wake_word`` decides whether a recognized (STT) transcript contains a
configured wake phrase. It is the only business logic behind the WS wake gate,
so it is tested directly with no I/O.
"""

from __future__ import annotations

from app.domain.wakeword.value_objects import (
    _levenshtein,
    canonicalize_wake_word,
    matches_wake_word,
)


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


# -- Levenshtein distance ----------------------------------------------------


def test_levenshtein_identical_is_zero() -> None:
    assert _levenshtein("ベルちゃん", "ベルちゃん") == 0


def test_levenshtein_empty_operands() -> None:
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("", "") == 0


def test_levenshtein_single_substitution() -> None:
    # ベルちゃん vs ベルちゃ子: one substitution at the tail.
    assert _levenshtein("ベルちゃん", "ベルちゃ子") == 1
    # The real-world garble "ねるちゃん" differs from "ベルちゃん" in TWO
    # positions (ベ->ね AND katakana ル -> hiragana る), so it is distance 2.
    assert _levenshtein("ベルちゃん", "ねるちゃん") == 2


def test_levenshtein_insertion_and_deletion() -> None:
    assert _levenshtein("kitten", "sitting") == 3
    assert _levenshtein("abc", "ab") == 1
    assert _levenshtein("ab", "abc") == 1


# -- Fuzzy wake matching (ADR-0018) ------------------------------------------

_FUZZY_WAKE = ["ベルちゃん"]


def test_fuzzy_matches_single_substitution_garble() -> None:
    # ねるちゃん / ピルちゃん are dist 1; ピリちゃん is dist 2.
    assert matches_wake_word("ねるちゃん、こんにちは", _FUZZY_WAKE, 2)
    assert matches_wake_word("ピルちゃん", _FUZZY_WAKE, 2)
    assert matches_wake_word("ピリちゃん", _FUZZY_WAKE, 2)


def test_fuzzy_matches_garble_inside_longer_transcript() -> None:
    assert matches_wake_word("ねえ、ねるちゃんって元気？", _FUZZY_WAKE, 2)


def test_fuzzy_does_not_match_clearly_different_utterance() -> None:
    assert not matches_wake_word("今日はいい天気だね", _FUZZY_WAKE, 2)
    assert not matches_wake_word("おはようございます", _FUZZY_WAKE, 2)


def test_fuzzy_disabled_when_max_dist_zero() -> None:
    # Default behavior: exact/substring only, so a garble does not match.
    assert not matches_wake_word("ねるちゃん", _FUZZY_WAKE, 0)
    assert not matches_wake_word("ねるちゃん", _FUZZY_WAKE)  # default 0
    # An exact occurrence still matches with fuzzy off.
    assert matches_wake_word("ベルちゃん", _FUZZY_WAKE, 0)


def test_short_phrases_stay_exact_no_fuzzy_false_trigger() -> None:
    # len<=2 phrases ("ベル"/"エル") must NOT fuzzy-match a 1-edit neighbor,
    # otherwise they would false-trigger on almost anything.
    assert not matches_wake_word("ねる", ["ベル"], 2)
    assert not matches_wake_word("えり", ["エル"], 2)
    # ...but an exact/substring hit still works for short phrases.
    assert matches_wake_word("ベルだよ", ["ベル"], 2)


def test_fuzzy_respects_length_scaled_tolerance() -> None:
    # 3-char phrase ("ベルこ") tolerates only dist 1, not dist 2.
    assert matches_wake_word("ベルご", ["ベルこ"], 2)  # dist 1 -> match
    assert not matches_wake_word("ねるこ", ["ベルこ"], 2)  # dist 2 on a 3-char phrase


def test_canonicalize_rewrites_fuzzy_garble_to_canonical() -> None:
    # No exact variant configured; only the canonical. A fuzzy garble is
    # corrected to the canonical name for the LLM.
    assert (
        canonicalize_wake_word("ねるちゃん、こんにちは", _FUZZY_WAKE, "ベルちゃん", 2)
        == "ベルちゃん、こんにちは"
    )


def test_canonicalize_fuzzy_mid_sentence() -> None:
    assert (
        canonicalize_wake_word("ねえ、ピルちゃんって元気？", _FUZZY_WAKE, "ベルちゃん", 2)
        == "ねえ、ベルちゃんって元気？"
    )


def test_canonicalize_fuzzy_disabled_leaves_garble() -> None:
    # max_dist=0 -> no fuzzy correction, garble passes through.
    assert canonicalize_wake_word("ねるちゃん", _FUZZY_WAKE, "ベルちゃん", 0) == "ねるちゃん"


def test_canonicalize_exact_wins_over_fuzzy() -> None:
    # An exact configured variant is replaced even with fuzzy enabled.
    assert canonicalize_wake_word("レルちゃん、やあ", _WORDS, _CANON, 2) == "ベルちゃん、やあ"
