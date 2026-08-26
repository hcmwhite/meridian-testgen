"""The ``--prompt-debug`` prompt log for the mapper (D31, D32).

Off by default and free when off: nothing here runs, and no file is created,
unless the CLI builds a :class:`PromptLog` and hands it to the backend. When
it does, every prompt the backend sends is appended to
``prompts-mapper-<timestamp>.log`` in the directory the artifacts are
written to, each record preceded by a header line carrying the ISO
timestamp of when it was sent.

The file itself is created lazily, on the first prompt, so a run that asks for
the log and then sends nothing leaves no empty file behind.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

TOOL = "mapper"
# The separator that opens each record; the timestamp follows it.
HEADER_PREFIX = "=== prompt"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(moment: "datetime | None" = None) -> str:
    """An ISO-8601 UTC timestamp, seconds resolution, ``Z``-suffixed."""
    moment = moment if moment is not None else _now()
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _filename_stamp(moment: datetime) -> str:
    """The same instant, in a form that is safe in a filename."""
    return utc_stamp(moment).replace(":", "").replace("-", "")


class PromptLog:
    """Append-only log of the prompts one run sent.

    *clock* is a seam for tests — a zero-argument callable returning a
    ``datetime``; production uses the wall clock.
    """

    def __init__(self, out_dir, tool: str = TOOL, clock=None):
        self._clock = clock if clock is not None else _now
        self.tool = tool
        self.out_dir = Path(out_dir)
        self.path = self.out_dir / f"prompts-{tool}-{_filename_stamp(self._clock())}.log"
        self.count = 0

    def write(self, prompt: str) -> None:
        """Append one prompt, under its own ISO-timestamped header."""
        self.count += 1
        header = f"{HEADER_PREFIX} {self.count} {utc_stamp(self._clock())} ==="
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{header}\n{prompt}\n\n")
