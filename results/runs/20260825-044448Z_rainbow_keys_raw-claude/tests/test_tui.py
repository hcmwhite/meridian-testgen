"""Tests for the text-mode UI helpers in `tui` -- character mapping, ANSI
color conversion, and the rendered keyboard row.

`tui.main()` needs a real terminal, so it is not exercised here; the pure
presentation helpers it relies on are.
"""

from __future__ import annotations

import io

import pytest

import tui
from key_mapping import all_colors, color_for_key, key_order


def test_every_playable_key_has_a_stdin_character():
    assert set(tui._CHAR_TO_KEY.values()) == set(key_order())
    assert len(tui._CHAR_TO_KEY) == 10


@pytest.mark.parametrize(
    "char, key",
    [("a", "a"), ("g", "g"), ("j", "j"), (";", "semicolon"), ("'", "quote")],
)
def test_character_maps_to_logical_key_name(char, key):
    assert tui._CHAR_TO_KEY[char] == key


def test_non_playable_characters_are_unmapped():
    for char in ("q", "z", "1", " "):
        assert tui._CHAR_TO_KEY.get(char) is None


@pytest.mark.parametrize(
    "hex_color, expected",
    [
        ("#FF0000", "\x1b[38;2;255;0;0m"),
        ("#00FF00", "\x1b[38;2;0;255;0m"),
        ("#0000FF", "\x1b[38;2;0;0;255m"),
        ("#4B0082", "\x1b[38;2;75;0;130m"),
    ],
)
def test_ansi_color_converts_hex_to_truecolor_escape(hex_color, expected):
    assert tui._ansi_color(hex_color) == expected


def test_ansi_color_handles_every_mapped_key_color():
    for color in all_colors():
        escape = tui._ansi_color(color)
        assert escape.startswith("\x1b[38;2;") and escape.endswith("m")


@pytest.fixture
def draw(monkeypatch):
    def _draw(active):
        out = io.StringIO()
        monkeypatch.setattr(tui.sys, "stdout", out)
        tui._draw(set(active))
        return out.getvalue()
    return _draw


def test_draw_renders_all_ten_key_labels(draw):
    rendered = draw(set())
    for label in ("A", "S", "D", "F", "G", "J", "K", "L", ";", "'"):
        assert f" {label} " in rendered


def test_draw_uses_each_keys_assigned_color(draw):
    rendered = draw(set())
    for key in key_order():
        assert tui._ansi_color(color_for_key(key)) in rendered


def test_draw_marks_only_active_keys_with_inverse_video(draw):
    rendered = draw({"d"})
    assert rendered.count("\x1b[7m") == 1
    assert "\x1b[7m D " in rendered


def test_draw_can_mark_the_three_note_maximum_simultaneously(draw):
    rendered = draw({"a", "k", "quote"})
    assert rendered.count("\x1b[7m") == 3


def test_draw_separates_the_two_hand_groups(draw):
    rendered = draw(set())
    assert rendered.index(" G ") < rendered.index("  ") < rendered.index(" J ")


def test_draw_rewrites_the_current_line_and_shows_the_quit_hint(draw):
    rendered = draw(set())
    assert rendered.startswith("\r\x1b[K")
    assert rendered.endswith("(q to quit)")


def test_release_timeout_exceeds_typical_autorepeat_delay():
    assert tui.RELEASE_TIMEOUT_SECONDS > 0.5
