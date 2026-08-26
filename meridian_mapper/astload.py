"""Read a stage-1 ``ast.json`` into the model, and slice source by bytes.

The mapper consumes the parser's *output file*, never its internals (D8), so
everything this module knows about stage 1 is the schema-v2 envelope: a
top-level object carrying ``schema_version``, ``tool``, ``generated_at``,
``input_dir``, ``git_commit`` and ``python``, with the records under a
``units`` key.

Only the units of ``ast.json`` are the mapper's universe; ``excluded.json``
is outside it entirely (D9) and this module will not load one.
"""

from __future__ import annotations

import json
from pathlib import Path

from meridian_mapper import AST_SCHEMA_VERSION
from meridian_mapper.model import AstFunction, MapperModel


class AstLoadError(Exception):
    """The input file is not a readable stage-1 ``ast.json``."""


def load_ast_json(path) -> MapperModel:
    """Load *path* into a fresh :class:`MapperModel`.

    Raises :class:`AstLoadError` — naming the file — when the file is missing,
    is not JSON, is not a schema-v2 envelope, or holds a malformed unit.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AstLoadError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AstLoadError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AstLoadError(
            f"{path} is not a schema v{AST_SCHEMA_VERSION} ast.json: expected a "
            f"top-level object with a 'schema_version' field, found "
            f"{type(data).__name__}"
        )
    if "schema_version" not in data:
        raise AstLoadError(
            f"{path} has no 'schema_version': this stage reads stage-1 ast.json "
            f"schema v{AST_SCHEMA_VERSION}"
        )
    version = data["schema_version"]
    if version != AST_SCHEMA_VERSION:
        raise AstLoadError(
            f"{path} has schema_version {version!r}; this stage reads only "
            f"schema v{AST_SCHEMA_VERSION}"
        )
    units = data.get("units")
    if not isinstance(units, list):
        raise AstLoadError(f"{path} has no 'units' array")

    model = MapperModel(source_meta={k: v for k, v in data.items() if k != "units"})
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise AstLoadError(f"{path}: unit {index} is not an object")
        missing = [f for f in ("unit_id", "file_path", "start_byte", "end_byte")
                   if f not in unit]
        if missing:
            raise AstLoadError(
                f"{path}: unit {index} is missing {', '.join(missing)}"
            )
        unit_id = unit["unit_id"]
        if unit_id in model.functions:
            raise AstLoadError(f"{path}: duplicate unit_id {unit_id!r}")
        model.functions[unit_id] = AstFunction(unit_id=unit_id, record=unit)
    return model


def source_slice(codebase_root, function) -> str:
    """The exact definition text of *function*, sliced by byte offsets.

    Byte slicing — not line slicing — is the correct primitive: stage 1's
    ``start_byte``/``end_byte`` are exact on every file, while its columns are
    byte offsets that disagree with character indices on non-ASCII lines.

    *function* is an :class:`~meridian_mapper.model.AstFunction`. The result is
    decoded UTF-8, so a snippet quoted from it compares as text.
    """
    path = Path(codebase_root) / function.file_path
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AstLoadError(
            f"cannot read source for {function.unit_id}: {path}: "
            f"{exc.strerror or exc}"
        ) from exc
    start, end = function.start_byte, function.end_byte
    if not 0 <= start <= end <= len(data):
        raise AstLoadError(
            f"byte span {start}:{end} of {function.unit_id} is outside {path} "
            f"({len(data)} bytes) — the codebase may have changed since it was "
            f"parsed"
        )
    return data[start:end].decode("utf-8")
