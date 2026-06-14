"""Tests for speech text normalization (strip non-spoken content for TTS)."""

from __future__ import annotations

from app.domain.speech.text_normalization import sanitize_for_speech


def test_strips_bare_urls() -> None:
    assert sanitize_for_speech("詳しくは https://example.com/foo を見てね") == "詳しくは を見てね"
    assert "http" not in sanitize_for_speech("www.example.com にあります")


def test_markdown_link_keeps_label_drops_url() -> None:
    assert sanitize_for_speech("[公式サイト](https://example.com) を確認") == "公式サイト を確認"


def test_drops_code_fences_and_inline_backticks() -> None:
    text = "実行するには\n```bash\nrm -rf /\n```\n`ls` と打ちます"
    out = sanitize_for_speech(text)
    assert "rm -rf" not in out
    assert "`" not in out
    assert "ls と打ちます" in out


def test_strips_headings_bullets_emphasis() -> None:
    text = "# 見出し\n- 一つ目\n- 二つ目\n**強調**したい"
    out = sanitize_for_speech(text)
    assert "#" not in out and "*" not in out
    assert "見出し" in out and "一つ目" in out and "強調したい" in out


def test_plain_prose_unchanged() -> None:
    s = "こんにちは、今日はいい天気ですね。"
    assert sanitize_for_speech(s) == s


def test_empty_after_strip_falls_back_to_original() -> None:
    assert sanitize_for_speech("https://only-a-url.example") == "https://only-a-url.example"
