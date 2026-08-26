"""Note on/off logic, the 3-note simultaneity limit, and real-time audio synthesis.

Implements Requirement 1.3 (simultaneous note limit) and 1.4 (note
duration tied to key-down/key-up), plus the tone generation those
requirements imply. This module owns every "is a note currently
sounding" decision; callers only report raw key transitions and are
notified back of the resulting active/inactive state per key.
"""

from __future__ import annotations

import math
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from key_mapping import frequency_for_key

SAMPLE_RATE = 44100
BLOCK_SIZE = 256             # ~5.8ms per audio callback -- keeps input-to-sound latency low
MAX_SIMULTANEOUS_NOTES = 3   # Req 1.3

_ATTACK_SECONDS = 0.005      # short declick ramp -- inaudible, not a "hang time" after key-up
_RELEASE_SECONDS = 0.02
_PER_VOICE_AMPLITUDE = 0.25  # headroom so overlapping voices during a release tail don't clip


class _Voice:
    """One sounding (or releasing) note. Owned entirely by `NoteEngine`."""

    def __init__(self, key: str, frequency_hz: float):
        self.key = key
        self.finished = False
        self._phase = 0.0
        self._phase_increment = 2.0 * math.pi * frequency_hz / SAMPLE_RATE
        self._attack_samples = max(1, int(_ATTACK_SECONDS * SAMPLE_RATE))
        self._release_samples = max(1, int(_RELEASE_SECONDS * SAMPLE_RATE))
        self._samples_rendered = 0
        self._releasing_since: Optional[int] = None

    def note_off(self) -> None:
        self._releasing_since = self._samples_rendered

    def render(self, frame_count: int) -> np.ndarray:
        sample_indices = self._samples_rendered + np.arange(frame_count)
        phases = self._phase + self._phase_increment * np.arange(frame_count)
        wave = np.sin(phases)

        envelope = np.minimum(1.0, sample_indices / self._attack_samples)
        if self._releasing_since is not None:
            released_for = sample_indices - self._releasing_since
            release_envelope = np.maximum(0.0, 1.0 - released_for / self._release_samples)
            envelope = np.minimum(envelope, release_envelope)
            if release_envelope[-1] <= 0.0:
                self.finished = True

        self._phase = (self._phase + self._phase_increment * frame_count) % (2.0 * math.pi)
        self._samples_rendered += frame_count

        return (wave * envelope * _PER_VOICE_AMPLITUDE).astype(np.float32)


StateChangeCallback = Callable[[str, bool], None]


class NoteEngine:
    """Owns note-on/off decisions, the 3-voice simultaneity limit (Req 1.3), and audio output.

    A key pressed while 3 notes are already sounding is held as "pending":
    no note starts for it until a currently-sounding note's key is
    released, at which point the longest-waiting pending key (if still
    held) starts sounding immediately (Req 1.3, 1.4).
    """

    def __init__(self, on_state_change: Optional[StateChangeCallback] = None):
        self._on_state_change = on_state_change
        self._lock = threading.Lock()
        self._active: dict[str, _Voice] = {}
        # A list, not a dict keyed by key name: the same key can be re-pressed and
        # re-released while an earlier release tail for it is still fading out, and
        # both tail voices must be allowed to finish independently.
        self._releasing: list[_Voice] = []
        self._pending: list[str] = []

        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()

    def key_down(self, key: str) -> None:
        """Req 1.4: a note begins sounding on key-down, subject to the Req 1.3 voice limit."""
        event: Optional[tuple[str, bool]] = None
        with self._lock:
            if key in self._active or key in self._pending:
                return  # already sounding, or already waiting -- ignore duplicate key-down
            if len(self._active) < MAX_SIMULTANEOUS_NOTES:
                self._active[key] = _Voice(key, frequency_for_key(key))
                event = (key, True)
            else:
                self._pending.append(key)
        if event:
            self._emit(*event)

    def key_up(self, key: str) -> None:
        """Req 1.4: a note stops sounding on key-up; frees a slot for a pending key (Req 1.3)."""
        events: list[tuple[str, bool]] = []
        with self._lock:
            if key in self._active:
                voice = self._active.pop(key)
                voice.note_off()
                self._releasing.append(voice)
                events.append((key, False))
                if self._pending:
                    next_key = self._pending.pop(0)
                    self._active[next_key] = _Voice(next_key, frequency_for_key(next_key))
                    events.append((next_key, True))
            elif key in self._pending:
                self._pending.remove(key)  # released while waiting; it never sounded
        for changed_key, active in events:
            self._emit(changed_key, active)

    def _emit(self, key: str, active: bool) -> None:
        if self._on_state_change:
            self._on_state_change(key, active)

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        mix = np.zeros(frames, dtype=np.float32)
        with self._lock:
            for voice in list(self._active.values()) + self._releasing:
                mix += voice.render(frames)
            self._releasing = [v for v in self._releasing if not v.finished]
        outdata[:, 0] = mix
