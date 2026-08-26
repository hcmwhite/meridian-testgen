from __future__ import annotations

import numpy as np
import pytest

import audio_logic


class FakeOutputStream:
    instances: list["FakeOutputStream"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False
        FakeOutputStream.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def engine(monkeypatch):
    FakeOutputStream.instances.clear()
    monkeypatch.setattr(audio_logic.sd, "OutputStream", FakeOutputStream)
    changes: list[tuple[str, bool]] = []
    note_engine = audio_logic.NoteEngine(changes.append)
    yield note_engine, changes
    note_engine.close()


def test_engine_configures_and_closes_its_audio_stream(engine) -> None:
    note_engine, _ = engine
    stream = FakeOutputStream.instances[0]

    assert stream.started is True
    assert stream.kwargs["samplerate"] == audio_logic.SAMPLE_RATE
    assert stream.kwargs["callback"] == note_engine._audio_callback

    note_engine.close()
    assert stream.stopped is True
    assert stream.closed is True


def test_note_down_and_up_emit_sounding_state_changes(engine) -> None:
    note_engine, changes = engine

    note_engine.key_down("a")
    note_engine.key_down("a")  # duplicate key-down must not create another voice
    note_engine.key_up("a")
    note_engine.key_up("a")

    assert changes == [("a", True), ("a", False)]
    assert "a" not in note_engine._active
    assert len(note_engine._releasing) == 1


def test_fourth_held_key_waits_then_starts_in_fifo_order(engine) -> None:
    note_engine, changes = engine

    for key in ("a", "s", "d", "f", "g"):
        note_engine.key_down(key)

    assert set(note_engine._active) == {"a", "s", "d"}
    assert note_engine._pending == ["f", "g"]
    assert changes == [("a", True), ("s", True), ("d", True)]

    note_engine.key_up("s")
    note_engine.key_up("a")

    assert set(note_engine._active) == {"d", "f", "g"}
    assert note_engine._pending == []
    assert changes == [
        ("a", True), ("s", True), ("d", True),
        ("s", False), ("f", True), ("a", False), ("g", True),
    ]


def test_releasing_a_pending_key_prevents_it_from_starting(engine) -> None:
    note_engine, changes = engine
    for key in ("a", "s", "d", "f"):
        note_engine.key_down(key)

    note_engine.key_up("f")
    note_engine.key_up("a")

    assert set(note_engine._active) == {"s", "d"}
    assert changes == [("a", True), ("s", True), ("d", True), ("a", False)]


def test_audio_callback_mixes_active_voice_and_removes_finished_release(engine) -> None:
    note_engine, _ = engine
    note_engine.key_down("a")
    outdata = np.zeros((64, 1), dtype=np.float32)

    note_engine._audio_callback(outdata, 64, None, None)
    assert np.any(outdata != 0)

    note_engine.key_up("a")
    note_engine._audio_callback(
        np.zeros((audio_logic._Voice("a", 1)._release_samples + 2, 1), dtype=np.float32),
        audio_logic._Voice("a", 1)._release_samples + 2,
        None,
        None,
    )
    assert note_engine._releasing == []
