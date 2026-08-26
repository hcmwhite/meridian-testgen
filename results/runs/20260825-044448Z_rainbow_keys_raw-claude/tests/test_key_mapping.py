"""Tests for `key_mapping` -- key ordering, pitch assignment (Req 1.1/1.2)
and color assignment (Req 2.3)."""

from __future__ import annotations

import pytest

import key_mapping
from key_mapping import all_colors, color_for_key, frequency_for_key, key_order

ROYGBIV = ("#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF", "#4B0082", "#9400D3")


def test_ten_playable_keys_in_physical_order():
    assert key_order() == (
        "a", "s", "d", "f", "g",
        "j", "k", "l", "semicolon", "quote",
    )
    assert len(key_order()) == 10
    assert len(set(key_order())) == 10


def test_pitch_ascends_left_to_right():
    frequencies = [frequency_for_key(key) for key in key_order()]
    assert frequencies == sorted(frequencies)
    assert all(
        later > earlier
        for earlier, later in zip(frequencies, frequencies[1:])
    )


def test_second_octave_is_exactly_one_octave_above_the_first():
    lower = key_order()[:5]
    upper = key_order()[5:]
    for low_key, high_key in zip(lower, upper):
        assert frequency_for_key(high_key) == pytest.approx(
            2.0 * frequency_for_key(low_key)
        )


def test_lowest_key_is_middle_c():
    assert frequency_for_key("a") == pytest.approx(261.6255653, rel=1e-9)


@pytest.mark.parametrize(
    "key, semitones_above_c4",
    list(zip(
        ("a", "s", "d", "f", "g", "j", "k", "l", "semicolon", "quote"),
        (0, 2, 4, 7, 9, 12, 14, 16, 19, 21),
    )),
)
def test_major_pentatonic_semitone_offsets(key, semitones_above_c4):
    expected = 261.6255653005986 * (2.0 ** (semitones_above_c4 / 12.0))
    assert frequency_for_key(key) == pytest.approx(expected, rel=1e-12)


def test_frequency_for_unknown_key_raises():
    with pytest.raises(KeyError):
        frequency_for_key("z")


def test_colors_follow_roygbiv_wrapping_after_seven_keys():
    assert all_colors() == ROYGBIV + ROYGBIV[:3]


def test_color_for_key_matches_all_colors_ordering():
    assert tuple(color_for_key(key) for key in key_order()) == all_colors()


def test_every_key_has_a_valid_hex_color():
    for color in all_colors():
        assert len(color) == 7 and color.startswith("#")
        int(color[1:], 16)  # raises ValueError if not hex


def test_color_for_unknown_key_raises():
    with pytest.raises(KeyError):
        color_for_key("z")


def test_key_order_is_immutable_tuple_shared_by_module_constant():
    assert isinstance(key_order(), tuple)
    assert key_order() is key_mapping.KEY_ORDER


def test_all_colors_is_a_fresh_tuple_each_call():
    assert all_colors() == all_colors()
    assert isinstance(all_colors(), tuple)
