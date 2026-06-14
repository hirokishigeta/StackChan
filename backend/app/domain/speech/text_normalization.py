"""Normalize agent reply text into something worth *speaking* aloud.

The agent's ``text`` is read out by TTS, so content that exists only to be
*read on a screen* — URLs, markdown link/emphasis syntax, code blocks, file
paths — is noise (and sounds terrible) when voiced. This is a StackChan-side
concern (not the agent backend's): backends like HermesAgent legitimately
return URLs/code/tool output, and Hermes keeps the full text in its own memory;
we only strip it from what the device actually says.

Pairs with the prompt-side instruction in the agent gateway that asks the model
to keep ``text`` speech-friendly; this is the deterministic safety net for when
the model includes such content anyway.
"""

from __future__ import annotations

import re

# Fenced code blocks ```...``` (including the language hint) — drop entirely.
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
# Markdown links/images: [label](url) / ![alt](url) -> keep the human label.
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
# Bare URLs (http(s):// or www.). Match only ASCII URL characters (RFC 3986
# set) so the match STOPS at the first non-URL char — critically, Japanese has
# no spaces, so a `\S+` here would greedily eat the prose that follows a URL
# ("…https://x.com今日は晴れ" -> drops "今日は晴れ"). Do NOT use `\w` (it matches
# Japanese in Unicode mode); enumerate ASCII URL chars explicitly.
_BARE_URL = re.compile(
    r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.IGNORECASE,
)
# Inline code `x` -> x (drop the backticks, keep the word).
_INLINE_CODE = re.compile(r"`([^`]*)`")
# Leading markdown structure per line: headings (#), list bullets (-, *, +).
_LINE_PREFIX = re.compile(r"^[ \t]*(?:#{1,6}\s+|[-*+]\s+)", re.MULTILINE)
# Emphasis/symbol runs that are silent on screen but spoken as nothing useful.
_EMPHASIS = re.compile(r"(\*\*|\*|__|_|~~)")
# Collapse 3+ newlines and runs of spaces left by the removals.
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")


def sanitize_for_speech(text: str) -> str:
    """Return ``text`` reduced to what should be spoken aloud.

    Removes URLs, markdown link/emphasis syntax, fenced code blocks and inline
    backticks, and leading heading/bullet markers; collapses the whitespace the
    removals leave behind. Conservative: it strips *formatting and links*, not
    arbitrary words, so plain prose is unchanged. Returns the original (stripped)
    text if the result would be empty.
    """
    out = _CODE_FENCE.sub(" ", text)
    out = _MD_LINK.sub(r"\1", out)
    out = _BARE_URL.sub("", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _LINE_PREFIX.sub("", out)
    out = _EMPHASIS.sub("", out)
    out = _BLANK_LINES.sub("\n\n", out)
    out = _SPACES.sub(" ", out)
    out = "\n".join(line.strip() for line in out.splitlines())
    out = out.strip()
    return out or text.strip()
