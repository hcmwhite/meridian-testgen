"""Text-only terminal interface for Rainbow Keys.

Reuses the exact same logic layer as the Swift UI (`NoteEngine`,
`key_mapping`); only the presentation differs. Run with:

    python tui.py

Terminal caveat: terminals report key-presses (and auto-repeats) but not
key-releases, so "holding" a key is approximated: a note sounds while
auto-repeat events keep arriving for it and is released after
`RELEASE_TIMEOUT_SECONDS` without one. Enable/leave on key auto-repeat
for the best feel.
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty

from audio_logic import NoteEngine
from key_mapping import color_for_key, key_order

RELEASE_TIMEOUT_SECONDS = 0.55  # > typical initial auto-repeat delay

#: stdin character -> logical key name used by the logic layer
_CHAR_TO_KEY = {
    (";" if name == "semicolon" else "'" if name == "quote" else name): name
    for name in key_order()
}
_LABELS = {"semicolon": ";", "quote": "'"}


def _ansi_color(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


def _draw(active: set[str]) -> None:
    cells = []
    for name in key_order():
        label = _LABELS.get(name, name).upper()
        color = _ansi_color(color_for_key(name))
        if name in active:
            cells.append(f"{color}\x1b[7m {label} \x1b[0m")  # inverse video = lit
        else:
            cells.append(f"{color} {label} \x1b[0m")
        if name == "g":
            cells.append("  ")
    sys.stdout.write("\r\x1b[K" + "".join(cells) + "   (q to quit)")
    sys.stdout.flush()


def main() -> None:
    active: set[str] = set()  # keys we consider held (UI mirror of engine state)
    last_seen: dict[str, float] = {}

    def on_state_change(key: str, is_active: bool) -> None:
        if is_active:
            active.add(key)
        else:
            active.discard(key)
        _draw(active)

    engine = NoteEngine(on_state_change=on_state_change)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    print("Rainbow Keys (text mode) -- hold A S D F G / J K L ; ' to play\n")
    _draw(active)
    try:
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.03)
            now = time.monotonic()
            if ready:
                ch = sys.stdin.read(1).lower()
                if ch == "q":
                    break
                key = _CHAR_TO_KEY.get(ch)
                if key:
                    if key not in last_seen:
                        engine.key_down(key)
                    last_seen[key] = now
            for key, seen in list(last_seen.items()):
                if now - seen > RELEASE_TIMEOUT_SECONDS:
                    del last_seen[key]
                    engine.key_up(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        engine.close()
        print()


if __name__ == "__main__":
    main()
