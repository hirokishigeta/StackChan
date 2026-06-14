"""Wake word value objects (design-spec §4.4 / §8 / §11.6)."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WakeWordEntry:
    """A single registered wake word (design-spec §8.1).

    ``threshold`` is the detection sensitivity in the closed range [0, 1]
    (higher = stricter / fewer false positives). ``phrase`` must be a
    non-empty, non-whitespace string.
    """

    id: str
    phrase: str
    model_name: str = "default"
    threshold: float = 0.7
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.phrase or not self.phrase.strip():
            raise ValueError("wake word phrase must not be empty")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"wake word threshold must be within [0, 1], got {self.threshold!r}")


@dataclass(frozen=True)
class EndWordEntry:
    """A single end-of-conversation word (ADR-0016).

    While the backend wake gate is engaged, an utterance containing any enabled
    end word ends the conversation and returns the device to wake-waiting
    (ADR-0014). ``phrase`` must be a non-empty, non-whitespace string. Matched on
    the STT transcript text via :func:`matches_wake_word` (arbitrary Japanese,
    no extra model — same matching as wake words).
    """

    id: str
    phrase: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.phrase or not self.phrase.strip():
            raise ValueError("end word phrase must not be empty")


def _normalize_for_match(text: str) -> str:
    """Normalize a phrase for backend wake-word matching.

    Wake words may be arbitrary Japanese (ADR-0014), so we match on the STT
    transcript text rather than a model. To make the comparison robust against
    cosmetic differences we:

    - NFKC-normalize (folds full-width/half-width and compatibility forms so
      e.g. full-width and half-width kana/ASCII compare equal),
    - casefold (case-insensitive for any Latin characters in the phrase),
    - drop all whitespace and punctuation/symbol characters.

    The result keeps only letters/numbers so that "ねえ、スタックチャン！" and
    "ねえ スタックチャン" both reduce to the same key.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    out: list[str] = []
    for ch in normalized:
        if ch.isspace():
            continue
        category = unicodedata.category(ch)
        # Drop punctuation (P*) and symbols (S*); keep letters/numbers/marks.
        if category.startswith(("P", "S")):
            continue
        out.append(ch)
    return "".join(out)


def matches_wake_word(text: str, words: Iterable[str]) -> bool:
    """Return True if any wake phrase appears in ``text`` (normalized substring).

    Both the recognized text and each wake phrase are normalized via
    :func:`_normalize_for_match` (whitespace/punctuation stripped, casefolded,
    NFKC). A wake phrase matches when its normalized form is a non-empty
    substring of the normalized recognized text. Empty/blank phrases never
    match.
    """
    haystack = _normalize_for_match(text)
    if not haystack:
        return False
    for word in words:
        needle = _normalize_for_match(word)
        if needle and needle in haystack:
            return True
    return False


def canonicalize_wake_word(text: str, words: Sequence[str], canonical: str) -> str:
    """Replace the matched wake phrase in ``text`` with the ``canonical`` name.

    The backend STT often mis-transcribes the wake word (e.g. "ベルちゃん" heard
    as "レルちゃん"). We configure those variants so the wake gate still matches,
    but the raw garbled text would then reach the LLM. This corrects the
    recognized text before handing it to the agent so the model always sees the
    proper name (ADR-0017).

    Detection of *which* phrase occurs uses the same normalization as
    :func:`matches_wake_word`, but the replacement is performed on the raw
    ``text`` (so surrounding characters are preserved). The configured phrases
    are tried longest-first so a longer variant wins over a shorter partial hit.
    Only the first occurrence of the first matching phrase is replaced. When no
    configured phrase occurs (or ``canonical`` is blank), ``text`` is returned
    unchanged.
    """
    if not canonical:
        return text
    haystack = _normalize_for_match(text)
    if not haystack:
        return text
    # Longest configured phrases first so e.g. "ねえスタックチャン" beats
    # "スタックチャン" and we don't replace only the shorter substring.
    for word in sorted(words, key=len, reverse=True):
        if not _normalize_for_match(word):
            continue
        replaced = _replace_first_normalized(text, word, canonical)
        if replaced is not None:
            return replaced
    return text


def _replace_first_normalized(text: str, phrase: str, canonical: str) -> str | None:
    """Replace the first run in ``text`` that normalizes to contain ``phrase``.

    Walks the raw ``text`` and finds the shortest contiguous slice whose
    normalized form contains the normalized ``phrase``, then swaps that slice
    for ``canonical``. Returns the new string, or ``None`` if ``phrase`` does
    not occur. Operating on raw slices (rather than the normalized key) keeps
    punctuation/spacing around the match intact.
    """
    needle = _normalize_for_match(phrase)
    if not needle:
        return None
    n = len(text)
    # Find the earliest end at which some prefix-trimmed window matches, then
    # shrink the start as far right as possible so the replaced slice is the
    # tightest run that still contains the phrase (no surrounding chars eaten).
    for end in range(1, n + 1):
        if needle not in _normalize_for_match(text[:end]):
            continue
        start = 0
        while start < end and needle in _normalize_for_match(text[start + 1 : end]):
            start += 1
        return text[:start] + canonical + text[end:]
    return None
