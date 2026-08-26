"""Stdin/stdout JSON-lines bridge between the Swift UI process and the Python logic layer.

This file is glue only: it decodes raw key events coming from Swift,
forwards them to `NoteEngine`, and encodes `NoteEngine` / `key_mapping`
output back to Swift as JSON lines. It contains no note-selection,
color-assignment, or polyphony logic of its own -- see `key_mapping.py`
and `audio_logic.py` for that. It is also this process's entry point.

Protocol (newline-delimited JSON, one message per line):
  Swift -> Python:  {"type": "key_down", "key": "<key id>"}
                     {"type": "key_up",   "key": "<key id>"}
  Python -> Swift:  {"type": "colors", "keys": [...10 ids], "colors": [...10 hex]}
                     {"type": "note_state", "key": "<key id>", "active": true|false}

All diagnostic output must go to stderr, never stdout -- stdout is the
protocol channel and any stray text on it would corrupt the stream.
"""

from __future__ import annotations

import json
import sys

import key_mapping
from audio_logic import NoteEngine


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _send_colors() -> None:
    _send({
        "type": "colors",
        "keys": list(key_mapping.key_order()),
        "colors": list(key_mapping.all_colors()),
    })


def _send_note_state(key: str, active: bool) -> None:
    _send({"type": "note_state", "key": key, "active": active})


def run() -> None:
    engine = NoteEngine(on_state_change=_send_note_state)
    _send_colors()

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                print(f"bridge_server: ignoring malformed line: {line!r}", file=sys.stderr)
                continue

            message_type = message.get("type")
            key = message.get("key")
            if message_type == "key_down" and key:
                engine.key_down(key)
            elif message_type == "key_up" and key:
                engine.key_up(key)
    finally:
        engine.close()


if __name__ == "__main__":
    run()
