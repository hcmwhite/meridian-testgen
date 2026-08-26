"""Tests for `bridge_server` -- the JSON-lines protocol between Swift and Python.

The engine is replaced with a recording double so these tests cover only the
glue: decoding, dispatching, encoding, and stdout/stderr discipline.
"""

from __future__ import annotations

import io
import json

import pytest

import bridge_server
import key_mapping


class RecordingEngine:
    def __init__(self, on_state_change=None):
        self.on_state_change = on_state_change
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def key_down(self, key):
        self.calls.append(("down", key))

    def key_up(self, key):
        self.calls.append(("up", key))

    def close(self):
        self.closed = True


@pytest.fixture
def bridge(monkeypatch):
    """Run `bridge_server.run()` over scripted stdin; return (engine, messages, stderr)."""
    created: list[RecordingEngine] = []

    def factory(on_state_change=None):
        engine = RecordingEngine(on_state_change)
        created.append(engine)
        return engine

    monkeypatch.setattr(bridge_server, "NoteEngine", factory)

    def _run(stdin_text: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        monkeypatch.setattr(bridge_server.sys, "stdin", io.StringIO(stdin_text))
        monkeypatch.setattr(bridge_server.sys, "stdout", stdout)
        monkeypatch.setattr(bridge_server.sys, "stderr", stderr)
        bridge_server.run()
        lines = [line for line in stdout.getvalue().splitlines() if line]
        return created[-1], [json.loads(line) for line in lines], stderr.getvalue()

    return _run


def test_colors_message_is_sent_first(bridge):
    _, messages, _ = bridge("")
    assert messages[0] == {
        "type": "colors",
        "keys": list(key_mapping.key_order()),
        "colors": list(key_mapping.all_colors()),
    }
    assert len(messages[0]["keys"]) == 10
    assert len(messages[0]["colors"]) == 10


def test_key_events_are_forwarded_to_the_engine(bridge):
    stdin = "\n".join([
        json.dumps({"type": "key_down", "key": "a"}),
        json.dumps({"type": "key_up", "key": "a"}),
    ]) + "\n"
    engine, _, _ = bridge(stdin)
    assert engine.calls == [("down", "a"), ("up", "a")]


def test_blank_lines_are_skipped(bridge):
    engine, _, stderr = bridge('\n  \n{"type": "key_down", "key": "s"}\n\n')
    assert engine.calls == [("down", "s")]
    assert stderr == ""


def test_malformed_json_is_reported_on_stderr_and_does_not_stop_the_loop(bridge):
    engine, messages, stderr = bridge(
        'not json\n{"type": "key_down", "key": "d"}\n'
    )
    assert engine.calls == [("down", "d")]
    assert "malformed" in stderr
    # stdout still carries only protocol messages
    assert all(message["type"] in {"colors", "note_state"} for message in messages)


def test_unknown_message_types_are_ignored(bridge):
    engine, _, _ = bridge(json.dumps({"type": "explode", "key": "a"}) + "\n")
    assert engine.calls == []


def test_events_without_a_key_are_ignored(bridge):
    stdin = "\n".join([
        json.dumps({"type": "key_down"}),
        json.dumps({"type": "key_up", "key": ""}),
    ]) + "\n"
    engine, _, _ = bridge(stdin)
    assert engine.calls == []


def test_valid_json_that_is_not_an_object_currently_crashes_the_bridge(bridge):
    """Documents a real gap: only `json.JSONDecodeError` is guarded, so a
    well-formed non-object line (e.g. `[1, 2, 3]`) escapes as an
    AttributeError and tears down the bridge loop."""
    with pytest.raises(AttributeError):
        bridge("[1, 2, 3]\n")


def test_engine_is_closed_when_stdin_ends(bridge):
    engine, _, _ = bridge("")
    assert engine.closed


def test_note_state_callback_emits_protocol_messages(bridge, monkeypatch):
    engine, _, _ = bridge("")
    stdout = io.StringIO()
    monkeypatch.setattr(bridge_server.sys, "stdout", stdout)
    engine.on_state_change("semicolon", True)
    engine.on_state_change("semicolon", False)
    messages = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
    assert messages == [
        {"type": "note_state", "key": "semicolon", "active": True},
        {"type": "note_state", "key": "semicolon", "active": False},
    ]


def test_each_message_is_a_single_newline_terminated_line(bridge, monkeypatch):
    stdout = io.StringIO()
    monkeypatch.setattr(bridge_server.sys, "stdout", stdout)
    bridge_server._send({"type": "note_state", "key": "a", "active": True})
    text = stdout.getvalue()
    assert text.endswith("\n")
    assert text.count("\n") == 1
