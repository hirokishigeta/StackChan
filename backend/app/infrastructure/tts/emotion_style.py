"""Map the agent emotion vocabulary to Irodori-TTS emoji style controls.

Irodori-TTS steers prosody/affect with emoji appended to the text (ADR-0006).
The agent reply ``emotion`` is one of a small vocabulary (see the
OpenAICompatible gateway system prompt: neutral / happy / sad / angry / curious
/ surprised / sleepy). This table is the single source of truth for the
emotion -> emoji mapping; unknown values fall back to ``neutral`` (no emoji).

| emotion   | emoji | intent                      |
|-----------|-------|-----------------------------|
| neutral   | (none)| plain delivery              |
| happy     | 😊    | warm / cheerful             |
| sad       | 😢    | downcast                    |
| angry     | 😠    | irritated / stern           |
| curious   | 🤔    | inquisitive                 |
| surprised | 😲    | startled / excited          |
| sleepy    | 😴    | drowsy / low energy         |
"""

from __future__ import annotations

_EMOTION_EMOJI: dict[str, str] = {
    "neutral": "",
    "happy": "😊",
    "sad": "😢",
    "angry": "😠",
    "curious": "🤔",
    "surprised": "😲",
    "sleepy": "😴",
}


def style_text(*, text: str, emotion: str) -> str:
    """Return ``text`` with the emotion's style emoji appended (if any)."""
    emoji = _EMOTION_EMOJI.get(emotion, "")
    if not emoji:
        return text
    return f"{text}{emoji}"
