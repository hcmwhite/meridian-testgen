"""The live run log, and the incremental checkpoint.

Both exist for the same reason: a generation run spends real time and real
money, and until 2026-08-23 all of it lived only in process memory until the
final write — a kill at item 12 of 26 left nothing on disk and no record of
what had been done. Now:

* :class:`RunLog` — every progress line goes to stderr for the person
  watching AND, timestamped, to ``testgen_run.log`` in the output area, so a
  run can be followed (``tail -f``) and reconstructed after the fact.
* :class:`Checkpoint` — every item's outcome (a mechanically valid test, or
  exhaustion with its attempts) is appended to ``testgen_checkpoint.jsonl``
  the moment it is decided, and a restarted run loads the file and skips the
  items it already holds. The checkpoint is deleted after the final artifacts
  are written — it is crash insurance, not an output.

A checkpoint is only trusted when it was written from the same inputs: the
header line records the mapping artifact's ``generated_at``, and a mismatch
(the mapper was re-run in between) starts fresh with a say-so rather than
silently mixing two runs' work.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_LOG_NAME = "testgen_run.log"
CHECKPOINT_NAME = "testgen_checkpoint.jsonl"


class RunLog:
    """Progress lines, to stderr and to a timestamped file, or stderr only.

    ``RunLog(None)`` is the file-less fallback (unit tests, library callers):
    same interface, stderr only.
    """

    def __init__(self, out_dir: "Path | str | None"):
        self.path = Path(out_dir) / RUN_LOG_NAME if out_dir is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def say(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)
        if self.path is None:
            return
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {message}\n")


class Checkpoint:
    """Append-only record of decided items, one JSON line each.

    Line shapes:
    * header — ``{"source_generated_at": …}``, written when the file is
      created;
    * valid — ``{"unit_id", "requirement", "status": "valid", "source"}``;
    * exhausted — ``{"unit_id", "requirement", "status": "exhausted",
      "attempts": […]}``.
    """

    def __init__(self, out_dir: "Path | str | None", source_generated_at: str):
        self.path = (Path(out_dir) / CHECKPOINT_NAME
                     if out_dir is not None else None)
        self.source_generated_at = source_generated_at
        self.valid: dict = {}       # key -> source
        self.exhausted: dict = {}   # key -> attempts list
        self.stale = False
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
        header: dict = {}
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue    # a line cut off mid-write by the crash; skip it
            if "source_generated_at" in record:
                header = record
                continue
            key = (record.get("unit_id"), record.get("requirement"))
            if record.get("status") == "valid" and isinstance(
                    record.get("source"), str):
                self.valid[key] = record["source"]
            elif record.get("status") == "exhausted":
                self.exhausted[key] = record.get("attempts") or []
        if header.get("source_generated_at") != self.source_generated_at:
            # Written from different inputs: not resumable.
            self.stale = True
            self.valid.clear()
            self.exhausted.clear()

    @property
    def decided(self) -> set:
        return set(self.valid) | set(self.exhausted)

    def _append(self, record: dict) -> None:
        if self.path is None:
            return
        new_file = not self.path.exists() or self.stale
        mode = "w" if self.stale else "a"
        with self.path.open(mode, encoding="utf-8") as fh:
            if new_file:
                fh.write(json.dumps(
                    {"source_generated_at": self.source_generated_at}) + "\n")
            fh.write(json.dumps(record) + "\n")
        self.stale = False

    def record_valid(self, key: tuple, source: str) -> None:
        self.valid[key] = source
        self._append({"unit_id": key[0], "requirement": key[1],
                      "status": "valid", "source": source})

    def record_exhausted(self, key: tuple, attempts: list) -> None:
        self.exhausted[key] = attempts
        self._append({"unit_id": key[0], "requirement": key[1],
                      "status": "exhausted", "attempts": attempts})

    def clear(self) -> None:
        """Delete the file — the run completed and wrote its real outputs."""
        if self.path is not None:
            self.path.unlink(missing_ok=True)
