"""Map the agent emotion vocabulary to Irodori-TTS emoji style controls.

Irodori-TTS steers prosody/affect with emoji embedded in the text (ADR-0006);
stacking emoji intensifies the effect. This table is the single source of truth
for the emotion -> emoji mapping. The *voice character* itself (明るいが静かめの
少女の声) is driven by the VoiceDesign caption (``STACKCHAN_IRODORI_CAPTION``,
see :class:`AppSettings`); the per-emotion emoji here add transient expression
on top of that voice.

An optional persona *base style* emoji can be prepended to every utterance via
``STACKCHAN_IRODORI_BASE_STYLE``; it defaults to empty (disabled) so the caption
governs the baseline register and per-emotion emoji are not overridden by a
constant overlay. The base is configurable so the persona can be retuned
without code changes.

The agent reply ``emotion`` is one of a small vocabulary (see the
OpenAICompatible gateway system prompt: neutral / happy / sad / angry / curious
/ surprised / sleepy). ``shy``/``intimate`` are also mapped for future use.
Unknown values fall back to ``neutral`` (base style only, no extra emoji).

| emotion   | extra emoji | intent                                  |
|-----------|-------------|-----------------------------------------|
| neutral   | ⏸️          | calm, with a deliberate pause           |
| happy     | 🤭          | suppressed / shy smile                   |
| sad       | 😮‍💨😪      | sighing, low energy                      |
| angry     | (none)      | restrained — base 😏 only, not loud      |
| curious   | ⏸️🫣        | hesitant, peeking interest               |
| surprised | 🫣          | flustered, small startle                 |
| sleepy    | 😪          | drowsy                                   |
| shy       | 🫣🫶👂      | bashful, intimate                        |
| intimate  | 🫣🫶👂      | bashful, intimate                        |
"""

from __future__ import annotations

# Per-emotion emoji *appended* after the persona base style. Empty string means
# "no extra emoji beyond the base" (used for ``angry``: restrained, not loud).
_EMOTION_EMOJI: dict[str, str] = {
    "neutral": "⏸️",
    "happy": "🤭",
    "sad": "😮‍💨😪",
    "angry": "",
    "curious": "⏸️🫣",
    "surprised": "🫣",
    "sleepy": "😪",
    "shy": "🫣🫶👂",
    "intimate": "🫣🫶👂",
}

# Default persona base style; the synthesizer overrides this from settings.
# Empty by default: the VoiceDesign caption governs the baseline voice, so no
# constant emoji overlay is forced onto every utterance.
DEFAULT_BASE_STYLE = ""


def style_text(*, text: str, emotion: str, base_style: str = DEFAULT_BASE_STYLE) -> str:
    """Return ``text`` styled for the persona.

    The persona ``base_style`` (cool/introverted) is prepended and the emotion's
    emoji appended. Unknown emotions fall back to ``neutral`` so callers never
    crash on an unexpected label. When both base and extra are empty the text is
    returned unchanged.
    """
    extra = _EMOTION_EMOJI.get(emotion, _EMOTION_EMOJI["neutral"])
    return f"{base_style}{text}{extra}"
