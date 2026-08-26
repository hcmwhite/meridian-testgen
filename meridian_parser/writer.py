"""Streaming JSON array writer.

Records are serialised and written to disk one at a time; the writer never
accumulates them, so memory use does not grow with the number of records.
The same class serves both ``ast.json`` and ``excluded.json``.

When *meta* is given, the file is an object instead of a bare array: the
metadata fields first, then the records streamed under a ``units`` key.
The metadata describes the run — which tool, when, against what — so a
consumer loading the file later (or into a database) can tell one run from
another. The records themselves are unchanged either way.
"""

from __future__ import annotations

import json
import os


class WriterError(Exception):
    """The output file could not be opened (missing directory, no permission)."""


class JsonArrayWriter:
    """Stream records into a file as a valid JSON array.

    Usage::

        with JsonArrayWriter("ast.json") as w:
            w.write(record)

    The closing bracket is written by :meth:`close`, which the context manager
    calls even when the caller raises.
    """

    def __init__(self, path, meta=None):
        self.path = os.fspath(path)
        self._count = 0
        self._closed = False
        self._enveloped = meta is not None
        try:
            self._fh = open(self.path, "w", encoding="utf-8")
        except OSError as exc:
            directory = os.path.dirname(os.path.abspath(self.path))
            if not os.path.isdir(directory):
                raise WriterError(
                    "cannot write %s: directory %s does not exist" % (self.path, directory)
                ) from exc
            raise WriterError("cannot write %s: %s" % (self.path, exc.strerror or exc)) from exc
        if self._enveloped:
            self._fh.write("{\n")
            for key, value in meta.items():
                self._fh.write("  %s: %s,\n" % (json.dumps(key), json.dumps(value)))
            self._fh.write('  "units": [')
        else:
            self._fh.write("[")

    @property
    def count(self):
        """How many records have been written so far."""
        return self._count

    def write(self, record):
        """Serialise one record and append it to the array immediately."""
        if self._closed:
            raise WriterError("cannot write to a closed writer: %s" % self.path)
        if self._count:
            self._fh.write(",")
        indent = "\n    " if self._enveloped else "\n  "
        self._fh.write(indent + json.dumps(record, sort_keys=False))
        self._count += 1

    def close(self):
        """Write the closing bracket and close the file. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._count:
                self._fh.write("\n  ]" if self._enveloped else "\n]")
            else:
                self._fh.write("]")
            self._fh.write("\n}\n" if self._enveloped else "\n")
        finally:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
