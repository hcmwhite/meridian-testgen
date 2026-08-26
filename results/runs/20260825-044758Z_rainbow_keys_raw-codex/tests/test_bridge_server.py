from __future__ import annotations

import io
import json

import bridge_server
import key_mapping


class RecordingEngine:
    instances: list["RecordingEngine"] = []

    def __init__(self, on_state_change) -> None:
        self.on_state_change = on_state_change
        self.events: list[tuple[str, str]] = []
        self.closed = False
        RecordingEngine.instances.append(self)

    def key_down(self, key: str) -> None:
        self.events.append(("down", key))
        self.on_state_change(key, True)

    def key_up(self, key: str) -> None:
        self.events.append(("up", key))
        self.on_state_change(key, False)

    def close(self) -> None:
        self.closed = True


def test_send_colors_serializes_mapping_to_one_json_line(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(bridge_server.sys, "stdout", stdout)

    bridge_server._send_colors()

    assert json.loads(stdout.getvalue()) == {
        "type": "colors",
        "keys": list(key_mapping.key_order()),
        "colors": list(key_mapping.all_colors()),
    }


def test_run_forwards_only_valid_messages_and_closes_engine(monkeypatch) -> None:
    RecordingEngine.instances.clear()
    stdout, stderr = io.StringIO(), io.StringIO()
    stdin = io.StringIO(
        '\nnot-json\n{"type": "key_down", "key": "a"}\n'
        '{"type": "key_up", "key": "a"}\n{"type": "other", "key": "s"}\n'
        '{"type": "key_down", "key": ""}\n'
    )
    monkeypatch.setattr(bridge_server, "NoteEngine", RecordingEngine)
    monkeypatch.setattr(bridge_server.sys, "stdin", stdin)
    monkeypatch.setattr(bridge_server.sys, "stdout", stdout)
    monkeypatch.setattr(bridge_server.sys, "stderr", stderr)

    bridge_server.run()

    engine = RecordingEngine.instances[0]
    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert engine.events == [("down", "a"), ("up", "a")]
    assert engine.closed is True
    assert messages[0]["type"] == "colors"
    assert messages[1:] == [
        {"type": "note_state", "key": "a", "active": True},
        {"type": "note_state", "key": "a", "active": False},
    ]
    assert "ignoring malformed line" in stderr.getvalue()
