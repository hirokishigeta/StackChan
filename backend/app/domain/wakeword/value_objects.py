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


# Phrases this short stay exact/substring only: a 1-edit window over a 1-2 char
# phrase would match almost anything, so fuzzy matching is never applied to them
# regardless of the configured global cap (ADR-0018).
_FUZZY_MIN_PHRASE_LEN = 3


def _levenshtein(a: str, b: str) -> int:
    """Levenshtein (edit) distance between ``a`` and ``b``.

    Pure Python, no external dependency (domain layer must not pull deps;
    CLAUDE.md). Single-row dynamic programming, O(len(a) * len(b)) time and
    O(len(b)) space. Insertions, deletions and substitutions each cost 1.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + cost,  # substitution
                )
            )
        previous = current
    return previous[-1]


def _fuzzy_tolerance(needle_len: int, max_dist: int) -> int:
    """Length-scaled edit-distance tolerance for a normalized wake phrase.

    Longer phrases tolerate more garbling without false-triggering: 0 for very
    short phrases, 1 for 3-4 char phrases, 2 for >=5 char phrases. The result is
    capped by ``max_dist`` (the global ``STACKCHAN_WAKE_FUZZY_MAX_DIST``); a cap
    of 0 disables fuzzy matching entirely (exact behavior). Phrases shorter than
    :data:`_FUZZY_MIN_PHRASE_LEN` always get 0 (stay exact/substring only).
    """
    if max_dist <= 0 or needle_len < _FUZZY_MIN_PHRASE_LEN:
        return 0
    if needle_len <= 4:
        scaled = 1
    else:
        scaled = 2
    return min(scaled, max_dist)


def _best_fuzzy_window(haystack: str, needle: str, tol: int) -> tuple[int, int] | None:
    """Return the (start, end) of the best window of ``haystack`` matching ``needle``.

    Scans contiguous windows of ``haystack`` whose length is within +/- ``tol``
    of ``len(needle)`` and returns the (start, end) slice with the smallest
    Levenshtein distance to ``needle``, provided that distance is <= ``tol``.
    Returns ``None`` when no window is within tolerance (or ``tol`` <= 0). Both
    inputs are expected to be already normalized.
    """
    if tol <= 0 or not needle or not haystack:
        return None
    n = len(haystack)
    needle_len = len(needle)
    best: tuple[int, int, int] | None = None  # (dist, start, end)
    for start in range(n):
        for length in range(max(1, needle_len - tol), needle_len + tol + 1):
            end = start + length
            if end > n:
                break
            dist = _levenshtein(haystack[start:end], needle)
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, start, end)
                if dist == 0:
                    return (start, end)
    if best is None:
        return None
    return (best[1], best[2])


def matches_wake_word(text: str, words: Iterable[str], max_dist: int = 0) -> bool:
    """Return True if any wake phrase appears in ``text`` (ADR-0014 / ADR-0018).

    Both the recognized text and each wake phrase are normalized via
    :func:`_normalize_for_match` (whitespace/punctuation stripped, casefolded,
    NFKC). A wake phrase matches when its normalized form is a non-empty
    substring of the normalized recognized text. Empty/blank phrases never
    match.

    When ``max_dist`` > 0, fuzzy (edit-distance) matching also engages: a phrase
    additionally matches when some contiguous window of the normalized text is
    within a length-scaled Levenshtein tolerance (see :func:`_fuzzy_tolerance`,
    capped by ``max_dist``) of the normalized phrase. This lets mis-transcribed
    wake words (e.g. "ねるちゃん" for "ベルちゃん") still engage. ``max_dist`` = 0
    (the default) preserves the exact/substring-only behavior for callers that do
    not opt in. The domain never reads settings: the caller passes the cap in.
    """
    haystack = _normalize_for_match(text)
    if not haystack:
        return False
    for word in words:
        needle = _normalize_for_match(word)
        if not needle:
            continue
        if needle in haystack:
            return True
        tol = _fuzzy_tolerance(len(needle), max_dist)
        if tol and _best_fuzzy_window(haystack, needle, tol) is not None:
            return True
    return False


def canonicalize_wake_word(
    text: str, words: Sequence[str], canonical: str, max_dist: int = 0
) -> str:
    """Replace the matched wake phrase in ``text`` with the ``canonical`` name.

    The backend STT often mis-transcribes the wake word (e.g. "ベルちゃん" heard
    as "レルちゃん" or "ねるちゃん"). We configure variants and/or fuzzy-match so
    the wake gate still engages, but the raw garbled text would then reach the
    LLM. This corrects the recognized text before handing it to the agent so the
    model always sees the proper name (ADR-0017 / ADR-0018).

    Detection of *which* phrase occurs uses the same normalization as
    :func:`matches_wake_word`, but the replacement is performed on the raw
    ``text`` (so surrounding characters are preserved). The configured phrases
    are tried longest-first so a longer variant wins over a shorter partial hit.
    Exact/substring hits take precedence over fuzzy ones. When ``max_dist`` > 0
    and no configured phrase occurs exactly, the best fuzzy window (same
    length-scaled tolerance as the gate) is replaced instead. Only the first
    matching phrase's span is replaced. When nothing matches (or ``canonical``
    is blank), ``text`` is returned unchanged.
    """
    if not canonical:
        return text
    haystack = _normalize_for_match(text)
    if not haystack:
        return text
    # Longest configured phrases first so e.g. "ねえスタックチャン" beats
    # "スタックチャン" and we don't replace only the shorter substring.
    ordered = sorted(words, key=len, reverse=True)
    # Exact/substring replacement takes precedence over fuzzy across all phrases.
    for word in ordered:
        if not _normalize_for_match(word):
            continue
        replaced = _replace_first_normalized(text, word, canonical)
        if replaced is not None:
            return replaced
    if max_dist <= 0:
        return text
    # No exact hit: fall back to replacing the best fuzzy-matched span so the
    # garble (e.g. "ねるちゃん") becomes the canonical name for the LLM.
    for word in ordered:
        needle = _normalize_for_match(word)
        tol = _fuzzy_tolerance(len(needle), max_dist)
        if not tol:
            continue
        window = _best_fuzzy_window(haystack, needle, tol)
        if window is not None:
            replaced = _replace_normalized_span(text, window, canonical)
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


def _replace_normalized_span(
    text: str, normalized_span: tuple[int, int], canonical: str
) -> str | None:
    """Replace the raw-text slice that maps to ``normalized_span`` with ``canonical``.

    ``normalized_span`` is a (start, end) half-open range over the *normalized*
    form of ``text`` (as produced by :func:`_normalize_for_match`). Because
    normalization drops whitespace/punctuation, we rebuild the mapping from each
    kept normalized character to its source index in the raw ``text`` and splice
    out the corresponding raw slice. Returns ``None`` if the span is empty or out
    of range.
    """
    n_start, n_end = normalized_span
    if n_end <= n_start:
        return None
    # raw index of each kept (normalized) character, in order. NFKC can change
    # length vs the raw text, so walk the raw text the same way
    # _normalize_for_match does and record the raw offset of each kept char.
    raw_indices: list[int] = []
    for raw_i, raw_ch in enumerate(text):
        for ch in unicodedata.normalize("NFKC", raw_ch).casefold():
            if ch.isspace():
                continue
            category = unicodedata.category(ch)
            if category.startswith(("P", "S")):
                continue
            raw_indices.append(raw_i)
    if n_end > len(raw_indices):
        return None
    raw_start = raw_indices[n_start]
    raw_end = raw_indices[n_end - 1] + 1
    return text[:raw_start] + canonical + text[raw_end:]
