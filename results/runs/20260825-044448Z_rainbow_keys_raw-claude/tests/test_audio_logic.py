"""Tests for `audio_logic.NoteEngine` -- the 3-note simultaneity limit (Req 1.3),
key-down/key-up note lifetime (Req 1.4), and the synthesis/envelope behaviour."""

from __future__ import annotations

import numpy as np
import pytest

import audio_logic
from audio_logic import (
    BLOCK_SIZE,
    MAX_SIMULTANEOUS_NOTES,
    SAMPLE_RATE,
    NoteEngine,
    _Voice,
)


class StateRecorder:
    """Records (key, is_active) pairs as the engine emits them."""

    def __init__(self):
        self.events: list[tuple[str, bool]] = []

    def __call__(self, key: str, is_active: bool) -> None:
        self.events.append((key, is_active))


@pytest.fixture
def collector():
    return StateRecorder()


# --- stream lifecycle ----------------------------------------------------

def test_engine_opens_and_starts_an_output_stream(engine_factory, stream_factory):
    engine_factory()
    stream = stream_factory()
    assert stream.started
    assert stream.kwargs["samplerate"] == SAMPLE_RATE
    assert stream.kwargs["blocksize"] == BLOCK_SIZE
    assert stream.kwargs["channels"] == 1
    assert stream.kwargs["dtype"] == "float32"


def test_close_stops_and_closes_the_stream(stream_factory):
    engine = NoteEngine()
    engine.close()
    stream = stream_factory()
    assert stream.stopped and stream.closed


# --- Req 1.4: note lifetime tied to key transitions ----------------------

def test_key_down_reports_active_and_key_up_reports_inactive(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    engine.key_down("a")
    assert collector.events == [("a", True)]
    engine.key_up("a")
    assert collector.events == [("a", True), ("a", False)]


def test_duplicate_key_down_is_ignored(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    engine.key_down("a")
    engine.key_down("a")
    engine.key_down("a")
    assert collector.events == [("a", True)]


def test_key_up_for_a_key_that_was_never_pressed_is_a_no_op(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    engine.key_up("a")
    assert collector.events == []


def test_key_can_be_replayed_after_release(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for _ in range(3):
        engine.key_down("s")
        engine.key_up("s")
    assert collector.events == [("s", True), ("s", False)] * 3


def test_engine_works_without_a_state_change_callback(engine_factory):
    engine = engine_factory()
    engine.key_down("a")
    engine.key_up("a")  # must not raise


# --- Req 1.3: at most three simultaneous notes ---------------------------

def test_at_most_three_notes_sound_at_once(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d", "f", "g"):
        engine.key_down(key)
    assert collector.events == [("a", True), ("s", True), ("d", True)]
    assert MAX_SIMULTANEOUS_NOTES == 3


def test_fourth_key_starts_sounding_when_a_slot_frees_up(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d", "f"):
        engine.key_down(key)
    collector.events.clear()
    engine.key_up("a")
    assert collector.events == [("a", False), ("f", True)]


def test_pending_keys_start_in_press_order(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d", "f", "g", "j"):
        engine.key_down(key)
    collector.events.clear()
    engine.key_up("a")
    engine.key_up("s")
    assert collector.events == [("a", False), ("f", True), ("s", False), ("g", True)]


def test_key_released_while_pending_never_sounds(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d", "f"):
        engine.key_down(key)
    collector.events.clear()
    engine.key_up("f")          # released while still waiting
    engine.key_up("a")          # frees a slot -- nothing pending should start
    assert collector.events == [("a", False)]


def test_repeat_key_down_while_pending_is_ignored(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d", "f"):
        engine.key_down(key)
    engine.key_down("f")
    collector.events.clear()
    engine.key_up("a")
    assert collector.events == [("a", False), ("f", True)]
    collector.events.clear()
    engine.key_up("s")
    assert collector.events == [("s", False)]  # 'f' was only queued once


def test_releasing_all_keys_allows_three_new_notes(engine_factory, collector):
    engine = engine_factory(on_state_change=collector)
    for key in ("a", "s", "d"):
        engine.key_down(key)
    for key in ("a", "s", "d"):
        engine.key_up(key)
    collector.events.clear()
    for key in ("j", "k", "l", "semicolon"):
        engine.key_down(key)
    assert collector.events == [("j", True), ("k", True), ("l", True)]


# --- audio rendering -----------------------------------------------------

def test_silence_when_no_key_is_held(engine_factory, render):
    engine = engine_factory()
    assert np.all(render(engine) == 0.0)


def test_held_key_produces_non_silent_audio(engine_factory, render):
    engine = engine_factory()
    engine.key_down("a")
    render(engine, BLOCK_SIZE)          # attack ramp
    block = render(engine, BLOCK_SIZE)
    assert np.max(np.abs(block)) > 0.1


def test_output_stays_within_float_range_with_three_notes(engine_factory, render):
    engine = engine_factory()
    for key in ("a", "s", "d"):
        engine.key_down(key)
    for _ in range(20):
        block = render(engine, BLOCK_SIZE)
        assert np.max(np.abs(block)) <= 1.0
        assert block.dtype == np.float32


def test_release_tail_fades_to_silence_and_voice_is_reclaimed(engine_factory, render):
    engine = engine_factory()
    engine.key_down("a")
    render(engine, BLOCK_SIZE)
    engine.key_up("a")
    # release is 20ms; render well past it
    total_blocks = int(0.2 * SAMPLE_RATE / BLOCK_SIZE)
    for _ in range(total_blocks):
        render(engine, BLOCK_SIZE)
    assert engine._releasing == []
    assert np.all(render(engine, BLOCK_SIZE) == 0.0)


def test_rapid_retrigger_keeps_both_release_tails_alive(engine_factory, render):
    engine = engine_factory()
    engine.key_down("a")
    render(engine, 64)
    engine.key_up("a")
    engine.key_down("a")
    render(engine, 64)
    engine.key_up("a")
    assert len(engine._releasing) == 2   # both tails fade independently


def test_only_the_released_key_stops_sounding(engine_factory, render):
    engine = engine_factory()
    engine.key_down("a")
    engine.key_down("j")
    render(engine, BLOCK_SIZE)
    engine.key_up("a")
    for _ in range(30):
        render(engine, BLOCK_SIZE)
    assert set(engine._active) == {"j"}
    assert np.max(np.abs(render(engine, BLOCK_SIZE))) > 0.1


# --- _Voice unit-level behaviour ----------------------------------------

def test_voice_renders_the_requested_frequency():
    frequency = 440.0
    voice = _Voice("a", frequency)
    frames = SAMPLE_RATE  # one second
    samples = voice.render(frames).astype(np.float64)
    spectrum = np.abs(np.fft.rfft(samples))
    peak_hz = np.fft.rfftfreq(frames, 1.0 / SAMPLE_RATE)[int(np.argmax(spectrum))]
    assert peak_hz == pytest.approx(frequency, abs=2.0)


def test_voice_attack_ramps_up_from_zero():
    voice = _Voice("a", 261.6255653005986)
    samples = voice.render(64)
    assert samples[0] == pytest.approx(0.0, abs=1e-6)
    assert np.max(np.abs(samples)) > 0.0


def test_voice_is_not_finished_until_release_completes():
    voice = _Voice("a", 440.0)
    voice.render(1024)
    assert not voice.finished
    voice.note_off()
    voice.render(int(0.01 * SAMPLE_RATE))
    assert not voice.finished          # mid-release
    voice.render(int(0.05 * SAMPLE_RATE))
    assert voice.finished


def test_voice_output_is_silent_after_release_finishes():
    voice = _Voice("a", 440.0)
    voice.render(1024)
    voice.note_off()
    voice.render(int(0.05 * SAMPLE_RATE))
    assert np.all(np.abs(voice.render(256)) == 0.0)


def test_voice_amplitude_is_bounded_by_per_voice_headroom():
    voice = _Voice("a", 440.0)
    samples = voice.render(SAMPLE_RATE // 10)
    assert np.max(np.abs(samples)) <= audio_logic._PER_VOICE_AMPLITUDE + 1e-6


def test_voice_phase_is_continuous_across_render_calls():
    frequency = 440.0
    voice = _Voice("a", frequency)
    joined = np.concatenate([voice.render(128), voice.render(128)])
    reference = _Voice("a", frequency).render(256)
    assert np.allclose(joined, reference, atol=1e-6)
