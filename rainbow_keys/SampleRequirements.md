# Rainbow Keys — Sample Requirements

A colorful pentatonic keyboard instrument for macOS. Plays sound when user
presses keys. Highlights via TUI to show the end user which key is pressed.

## 1. Sound

### 1.1 Key-to-Note Mapping
Ten playable keys — A, S, D, F, G and J, K, L, ;, ' — each map to one note
of a major pentatonic scale, in ascending pitch order from left to right.
The second group (J through ') sounds one octave above the first.

### 1.2 Note Lifetime
A note starts sounding on key-down and stops on key-up. Holding a key
sustains its note; no re-pressing is required.

### 1.3 Polyphony Limit
At most 3 notes sound simultaneously. A key pressed while 3 notes are
sounding waits (if still held) and begins sounding as soon as a slot frees.

### 1.4 Latency
Audible output begins within 20 ms of a key press, with no clicks or pops
at note start or stop.

## 2. Visual Feedback

### 2.1 Key Display
All 10 playable keys are shown on screen in physical keyboard order, each
in its assigned color, with a visible gap between the two octave groups.

### 2.2 Pressed-Key Highlight
While a key's note is sounding, its on-screen element is visibly
highlighted; it returns to normal when the note stops. A key waiting on the
polyphony limit (1.3) is not highlighted until it actually sounds.

### 2.3 Colors
Keys are colored following the ROYGBIV sequence, repeating as needed,
assigned left to right.

## 3. Interfaces

### 3.1 Graphical Interface
The primary interface is a native macOS window rendering the key display
per section 2.

### 3.2 Text Interface (TUI)
A text-only terminal interface offers the same instrument: it plays sound
when user presses keys, and highlights via TUI to show the end user which
key is pressed. It reuses the same sound logic as the graphical interface;
only presentation differs.

### 3.3 TUI Release Approximation
Because terminals do not report key-release events, the TUI may treat a key
as released after a short interval (≤ 0.6 s) without auto-repeat input for
it. This is the only permitted deviation from 1.2.

### 3.4 Quit
The TUI exits cleanly on `q`, restoring the terminal state and silencing
all notes.

## 4. Non-Functional

### 4.1 Shared Logic
Note mapping, polyphony, and synthesis live in a single logic layer shared
by all interfaces; interfaces only report raw key transitions and render
the resulting state.

### 4.2 Dependencies
The Python layer requires only NumPy and sounddevice; the TUI requires no
additional packages or macOS permissions.
