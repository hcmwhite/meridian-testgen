"""Pure key-to-note and key-to-color mapping for Rainbow Keys.

Implements Requirements 1.1, 1.2 (key -> pitch) and 2.3 (key -> color).
Contains no audio playback, no I/O, and no UI code -- only data and pure
functions, so it can be reasoned about independently of the rest of the
logic layer.
"""

from __future__ import annotations

# --- Requirement discrepancy note ---------------------------------------
# Requirements.md describes 10 playable keys (2.1) but originally
# enumerated only 9 (A S D F G / J K L ;). Resolved here by adding the
# Quote key (') immediately to the right of Semicolon on a physical
# QWERTY keyboard, completing Octave 2 as a 5-note pentatonic run
# (J K L ; ') that mirrors Octave 1 (A S D F G). See Requirements.md,
# "Appendix: Resolved Ambiguity" for the full rationale -- this remains
# an open item there in case the original intent differs.
# -------------------------------------------------------------------------

#: The 10 playable keys, left to right in physical keyboard order. This is
#: the single source of truth for key ordering; the UI is told this order
#: (paired with colors) rather than hardcoding pitch-relevant order itself.
KEY_ORDER: tuple[str, ...] = (
    "a", "s", "d", "f", "g",
    "j", "k", "l", "semicolon", "quote",
)

#: Semitone offsets from C4 for a major pentatonic scale (C D E G A),
#: repeated one octave higher for the second five keys. Ascending order
#: within each octave satisfies Req 1.1 / 1.2 (lowest key = lowest pitch).
_PENTATONIC_OCTAVE_1_SEMITONES: tuple[int, ...] = (0, 2, 4, 7, 9)
_SEMITONES_FROM_C4: tuple[int, ...] = _PENTATONIC_OCTAVE_1_SEMITONES + tuple(
    offset + 12 for offset in _PENTATONIC_OCTAVE_1_SEMITONES
)

#: C4, in Hz (A4 = 440Hz equal temperament). Requirements only constrain
#: relative/ascending pitch order, not absolute pitch, so this base is an
#: implementation choice.
_C4_FREQUENCY_HZ: float = 261.6255653005986

_FREQUENCY_BY_KEY: dict[str, float] = {
    key: _C4_FREQUENCY_HZ * (2.0 ** (semitones / 12.0))
    for key, semitones in zip(KEY_ORDER, _SEMITONES_FROM_C4)
}

#: ROYGBIV sequence (Req 2.3), repeated (wrapped) to cover all 10 keys.
_ROYGBIV_HEX: tuple[str, ...] = (
    "#FF0000",  # Red
    "#FF7F00",  # Orange
    "#FFFF00",  # Yellow
    "#00FF00",  # Green
    "#0000FF",  # Blue
    "#4B0082",  # Indigo
    "#9400D3",  # Violet
)

_COLOR_BY_KEY: dict[str, str] = {
    key: _ROYGBIV_HEX[index % len(_ROYGBIV_HEX)]
    for index, key in enumerate(KEY_ORDER)
}


def key_order() -> tuple[str, ...]:
    """The 10 playable keys, left to right (Req 2.1 ordering, 2.3 assignment order)."""
    return KEY_ORDER


def frequency_for_key(key: str) -> float:
    """The pitch, in Hz, assigned to `key` (Req 1.1, 1.2)."""
    return _FREQUENCY_BY_KEY[key]


def color_for_key(key: str) -> str:
    """The ROYGBIV hex color assigned to `key` (Req 2.3)."""
    return _COLOR_BY_KEY[key]


def all_colors() -> tuple[str, ...]:
    """Colors for all keys, in the same order as `key_order()`."""
    return tuple(_COLOR_BY_KEY[key] for key in KEY_ORDER)
