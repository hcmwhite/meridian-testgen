# Rainbow Keys — Requirements

## 1. Keyboard Input
Parent requirement covering all key-to-note behavior.

### 1.1 Octave 1 Mapping
The keys A, S, D, F, G map to the five notes of a pentatonic scale in the first octave, in ascending pitch order (A = lowest, G = highest of that octave).

### 1.2 Octave 2 Mapping
The keys J, K, L, and ; (semicolon) map to the same five-note pentatonic scale one octave higher than Octave 1, in ascending pitch order (J = lowest, ; = highest).

### 1.3 Simultaneous Note Limit
Up to 3 notes may sound at the same time. If a 4th key is pressed while 3 notes are already sounding, the 4th key press does not produce a new note until one of the currently-sounding notes is released.

### 1.4 Note Duration
A note begins sounding when its key is pressed (key-down) and stops sounding when that same key is released (key-up). Notes do not persist after key-up, and do not require repeated key presses to continue while held.

## 2. Visual Feedback
Parent requirement covering all on-screen key representation.

### 2.1 Key Buttons
Each of the 10 playable keys (A, S, D, F, G, J, K, L, ;, and one more to total 10 — see note below) is represented on screen as a distinct button-like visual element, arranged left to right in the same order as the physical keyboard layout.

### 2.2 Active Key Highlight
When a key is pressed and its note is sounding, that key's on-screen element changes to a visibly lighter shade of its assigned color. When the key is released, the element returns to its normal (non-lit) shade.

### 2.3 Color Assignment
The 10 playable keys are assigned colors following the ROYGBIV sequence (Red, Orange, Yellow, Green, Blue, Indigo, Violet), repeating or extending the sequence as needed to cover all 10 keys, assigned left to right in physical keyboard order.

---

## Appendix: Resolved Ambiguity — Open Item

**Status:** Resolved for implementation purposes; flagged here as an open item in case the original intent differs.

The original document above states there are 10 playable keys (2.1) but only enumerates 9 across the two key groups: Octave 1 (1.1) names A, S, D, F, G — 5 keys. Octave 2 (1.2) names J, K, L, ; — only 4 keys, one short of a second full 5-note pentatonic octave.

**Resolution chosen:** Octave 2 is extended with the Quote key (`'`), the physical key immediately to the right of Semicolon (`;`) on a standard QWERTY keyboard. This gives Octave 2 five keys — J, K, L, ;, ' — in ascending pitch order, mirroring Octave 1's five keys (A, S, D, F, G), for 10 playable keys total. This was chosen over alternatives (e.g. reusing a key from Octave 1's row, or a non-adjacent key) because it is the minimal, position-consistent extension of the exact row `J K L ;` the requirements already specify, preserving left-to-right / low-to-high physical ordering per 1.2, 2.1, and 2.3.

**Why this is still flagged as open:** requirements 1.1 and 1.2 as numbered do not mention Quote anywhere; if the original intent was a different 10th key (or a different Octave 1/2 split entirely), those two requirements should be amended and this appendix removed. Implementation (`python/key_mapping.py`) references this appendix directly in a comment at the point where the 10th key is introduced, so the discrepancy stays traceable from code back to this document.
