"""Wake word value objects (design-spec §4.4 / §8 / §11.6)."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class DetectionMethod(StrEnum):
    """Where wake-word detection runs (design-spec §8.3)."""

    LOCAL = "local"  # CoreS3-side detection
    BACKEND = "backend"  # PC-side detection


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
