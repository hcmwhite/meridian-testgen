"""Tests for meridian_parser.writer."""

import json
import os

import pytest

from meridian_parser.writer import JsonArrayWriter, WriterError


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_records_round_trip_in_order(tmp_path):
    records = [
        {"dotted_name": "a.b", "file_path": "a.py", "line_number": 1, "signature": "def b()"},
        {"dotted_name": "a.c", "file_path": "a.py", "line_number": 5, "signature": "def c(x: int) -> str"},
        {"dotted_name": "a.d", "file_path": "a.py", "line_number": 9, "signature": "def d()"},
    ]
    out = tmp_path / "ast.json"
    with JsonArrayWriter(out) as writer:
        for record in records:
            writer.write(record)

    parsed = json.loads(read(out))
    assert parsed == records
    assert [r["dotted_name"] for r in parsed] == ["a.b", "a.c", "a.d"]


def test_zero_records_produces_empty_array(tmp_path):
    out = tmp_path / "excluded.json"
    with JsonArrayWriter(out) as writer:
        assert writer.count == 0

    assert read(out).strip() == "[]"
    assert json.loads(read(out)) == []


def test_closing_bracket_written_when_caller_raises(tmp_path):
    out = tmp_path / "ast.json"
    with pytest.raises(RuntimeError):
        with JsonArrayWriter(out) as writer:
            writer.write({"dotted_name": "a.b"})
            raise RuntimeError("boom")

    assert json.loads(read(out)) == [{"dotted_name": "a.b"}]


def test_unicode_and_nested_values_survive(tmp_path):
    record = {"dotted_name": "m.f", "signature": "def f(s: str = 'né') -> None", "tags": [1, 2]}
    out = tmp_path / "ast.json"
    with JsonArrayWriter(out) as writer:
        writer.write(record)
    assert json.loads(read(out)) == [record]


def test_close_is_idempotent(tmp_path):
    out = tmp_path / "ast.json"
    writer = JsonArrayWriter(out)
    writer.write({"a": 1})
    writer.close()
    writer.close()
    assert json.loads(read(out)) == [{"a": 1}]


def test_write_after_close_raises_writer_error(tmp_path):
    writer = JsonArrayWriter(tmp_path / "ast.json")
    writer.close()
    with pytest.raises(WriterError):
        writer.write({"a": 1})


def test_missing_output_directory_gives_clear_error(tmp_path):
    target = tmp_path / "does_not_exist" / "ast.json"
    with pytest.raises(WriterError) as excinfo:
        JsonArrayWriter(target)
    message = str(excinfo.value)
    assert "does not exist" in message
    assert str(tmp_path / "does_not_exist") in message


def test_output_is_byte_identical_across_runs(tmp_path):
    records = [{"dotted_name": "m.f%d" % i, "line_number": i} for i in range(20)]
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    for path in (first, second):
        with JsonArrayWriter(path) as writer:
            for record in records:
                writer.write(record)
    assert read(first) == read(second)


def test_writer_does_not_accumulate_records(tmp_path):
    """Memory use must not grow with record count.

    Two independent checks: the writer object holds no container that grows
    with the records passed in, and records reach the file as they are written
    rather than at close.
    """
    out = tmp_path / "ast.json"
    total = 5000
    with JsonArrayWriter(out) as writer:
        for i in range(total):
            writer.write({"dotted_name": "m.f%d" % i, "line_number": i})

            for value in vars(writer).values():
                if isinstance(value, (list, dict, set, tuple, bytearray)):
                    assert len(value) <= 1, (
                        "writer retains a container of %d items" % len(value)
                    )

            if i == 10:
                # The first records are already on disk, long before close().
                writer._fh.flush()
                on_disk = read(out)
                assert '"m.f0"' in on_disk
                assert os.path.getsize(out) > 0

    assert len(json.loads(read(out))) == total


def test_meta_wraps_records_in_an_envelope(tmp_path):
    out = tmp_path / "ast.json"
    meta = {"schema_version": 2, "tool": "meridian-parser 0.2.0", "git_commit": None}
    with JsonArrayWriter(out, meta) as writer:
        writer.write({"dotted_name": "a.b"})

    doc = json.loads(read(out))
    assert doc["schema_version"] == 2
    assert doc["tool"] == "meridian-parser 0.2.0"
    assert doc["git_commit"] is None
    assert doc["units"] == [{"dotted_name": "a.b"}]


def test_meta_envelope_with_zero_records(tmp_path):
    out = tmp_path / "ast.json"
    with JsonArrayWriter(out, {"schema_version": 2}) as writer:
        pass

    doc = json.loads(read(out))
    assert doc == {"schema_version": 2, "units": []}
