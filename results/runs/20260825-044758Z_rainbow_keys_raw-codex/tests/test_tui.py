from __future__ import annotations

import io

import tui


def test_character_mapping_covers_every_playable_key() -> None:
    assert tui._CHAR_TO_KEY == {
        "a": "a", "s": "s", "d": "d", "f": "f", "g": "g",
        "j": "j", "k": "k", "l": "l", ";": "semicolon", "'": "quote",
    }


def test_ansi_color_converts_hex_channels_to_truecolor_escape() -> None:
    assert tui._ansi_color("#FF7F00") == "\x1b[38;2;255;127;0m"


def test_draw_marks_only_active_keys_with_inverse_video(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(tui.sys, "stdout", stdout)

    tui._draw({"a", "quote"})

    rendered = stdout.getvalue()
    assert "\x1b[7m A \x1b[0m" in rendered
    assert "\x1b[7m ' \x1b[0m" in rendered
    assert "\x1b[7m S \x1b[0m" not in rendered
    assert "(q to quit)" in rendered
