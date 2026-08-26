from __future__ import annotations

import math

import pytest

import key_mapping


def test_key_order_contains_the_complete_two_octave_layout() -> None:
    assert key_mapping.key_order() == (
        "a", "s", "d", "f", "g", "j", "k", "l", "semicolon", "quote"
    )


def test_frequencies_are_ascending_and_second_octave_doubles_first() -> None:
    frequencies = [key_mapping.frequency_for_key(key) for key in key_mapping.key_order()]

    assert frequencies == sorted(frequencies)
    for first_octave, second_octave in zip(frequencies[:5], frequencies[5:]):
        assert second_octave == pytest.approx(first_octave * 2)


def test_colors_follow_and_wrap_the_roygbiv_sequence() -> None:
    assert key_mapping.all_colors() == (
        "#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF",
        "#4B0082", "#9400D3", "#FF0000", "#FF7F00", "#FFFF00",
    )
    assert key_mapping.color_for_key("semicolon") == "#FF7F00"


@pytest.mark.parametrize("lookup", [key_mapping.frequency_for_key, key_mapping.color_for_key])
def test_unknown_keys_are_rejected(lookup) -> None:
    with pytest.raises(KeyError):
        lookup("not-a-playable-key")
