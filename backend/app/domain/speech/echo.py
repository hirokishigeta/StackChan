"""Detect when a recognized utterance is the bot's own TTS echoed back.

The CoreS3 has no acoustic echo cancellation, and the device buffers audio
ahead of the backend's half-duplex window, so the tail of a reply can still be
playing out of the speaker when the mic re-opens. That tail gets recognized as
"user" speech and, while the conversation is engaged, fed back to the agent —
the bot starts talking to itself, which is exactly why turns degrade after the
first one. The robust, device-independent guard is to drop a recognized
utterance that matches what the bot just said.

Pure + deterministic so it is unit-testable without audio.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Strip everything that ASR/punctuation noise varies on, so the comparison is
# about the spoken words, not formatting. Keep Japanese + latin + digits.
_KEEP = re.compile(r"[0-9A-Za-z぀-ヿ一-鿿ｦ-ﾟ]+")

# Below this many comparable characters, an utterance is too short to confidently
# call an echo (e.g. "うん" / "はい" are common real answers that may also appear
# inside a reply). Short noise is handled by the VAD energy threshold instead.
_MIN_ECHO_LEN = 5
# Fraction of the recognized text that must appear as one contiguous block inside
# the last reply to count as an echo (absorbs minor ASR mis-transcription).
_CONTIG_RATIO = 0.8


def _normalize(text: str) -> str:
    return "".join(_KEEP.findall(text)).lower()


def is_echo_of(recognized: str, last_reply: str) -> bool:
    """True if ``recognized`` looks like the bot's ``last_reply`` echoed back.

    Echo when the normalized recognized text (>= a few chars) is a substring of
    the normalized last reply, or an ~80%+ contiguous chunk of it (so a slightly
    mis-heard echo still matches). Short utterances are never treated as echo.
    """
    r = _normalize(recognized)
    rep = _normalize(last_reply)
    if len(r) < _MIN_ECHO_LEN or not rep:
        return False
    if r in rep:
        return True
    match = SequenceMatcher(None, r, rep).find_longest_match(0, len(r), 0, len(rep))
    return match.size >= max(_MIN_ECHO_LEN, int(len(r) * _CONTIG_RATIO))
