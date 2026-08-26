"""Read the two stage-2 artifacts into one :class:`TestgenModel` (D24).

Stage 3 consumes the mapper's *output files*, never its internals (D22), so
everything here knows about stage 2 is the artifact envelope: a top-level
object carrying ``schema_version`` and ``artifact``, with the records under
``units`` (Artifact 1) or ``requirements`` (Artifact 2).

Both files are checked before anything else happens: a v2 artifact, or the
requirements file passed where the ast file belongs, fails immediately with a
message naming the file, not later as a KeyError inside a prompt.
"""

from __future__ import annotations

import json
from pathlib import Path

from meridian_testgen import (
    ARTIFACT_MAPPING_AST,
    ARTIFACT_MAPPING_REQUIREMENTS,
    MAPPING_SCHEMA_VERSION,
)
from meridian_testgen.model import Requirement, TestgenFunction, TestgenModel


class InputError(Exception):
    """An input artifact is missing, malformed, or of the wrong kind."""


def _load_envelope(path, artifact: str, array_key: str) -> tuple[dict, list]:
    """Parse *path* and check it is the stage-2 *artifact*; return (meta, records)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(
            f"{path} is not a stage-2 {artifact} artifact: expected a top-level "
            f"object, found {type(data).__name__}"
        )

    version = data.get("schema_version")
    if version != MAPPING_SCHEMA_VERSION:
        raise InputError(
            f"{path} has schema_version {version!r}; this stage reads only "
            f"stage-2 schema v{MAPPING_SCHEMA_VERSION}"
        )
    found = data.get("artifact")
    if found != artifact:
        raise InputError(
            f"{path} is artifact {found!r}, not {artifact!r} — the two stage-2 "
            f"artifacts may be the wrong way round"
        )
    records = data.get(array_key)
    if not isinstance(records, list):
        raise InputError(f"{path} has no {array_key!r} array")
    meta = {k: v for k, v in data.items() if k != array_key}
    return meta, records


def load_mapping_ast(path, model=None) -> TestgenModel:
    """Load Artifact 1 (``mapping_ast.json``) into *model* (or a fresh one)."""
    model = model if model is not None else TestgenModel()
    meta, units = _load_envelope(path, ARTIFACT_MAPPING_AST, "units")
    model.ast_meta = meta
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise InputError(f"{path}: unit {index} is not an object")
        missing = [
            f for f in ("unit_id", "file_path", "start_byte", "end_byte")
            if f not in unit
        ]
        if missing:
            raise InputError(f"{path}: unit {index} is missing {', '.join(missing)}")
        unit_id = unit["unit_id"]
        if unit_id in model.functions:
            raise InputError(f"{path}: duplicate unit_id {unit_id!r}")
        model.functions[unit_id] = TestgenFunction(
            unit_id=unit_id,
            record=unit,
            requirement_codes=list(unit.get("requirement_codes") or []),
            tiers=dict(unit.get("verification") or {}),
            structural_test_only=bool(unit.get("structural_test_only", False)),
            error_notes=list(unit.get("error_notes") or []),
        )
    return model


def _requirement(node, path, index_path: str) -> Requirement:
    if not isinstance(node, dict):
        raise InputError(f"{path}: requirement at {index_path} is not an object")
    if "code" not in node:
        raise InputError(f"{path}: requirement at {index_path} has no 'code'")
    children = node.get("children") or []
    if not isinstance(children, list):
        raise InputError(
            f"{path}: requirement {node['code']!r} has a non-list 'children'"
        )
    return Requirement(
        code=str(node["code"]),
        text=str(node.get("text", "")),
        is_category=bool(node.get("is_category", False)),
        category_leak=bool(node.get("category_leak", False)),
        code_blocks=list(node.get("code_blocks") or []),
        children=[
            _requirement(child, path, f"{index_path}.{i}")
            for i, child in enumerate(children)
        ],
    )


def load_mapping_requirements(path, model=None) -> TestgenModel:
    """Load Artifact 2 (``mapping_requirements.json``) into *model*."""
    model = model if model is not None else TestgenModel()
    meta, nodes = _load_envelope(
        path, ARTIFACT_MAPPING_REQUIREMENTS, "requirements"
    )
    model.requirements_meta = meta
    model.requirements = [
        _requirement(node, path, str(i)) for i, node in enumerate(nodes)
    ]
    return model


def load_model(mapping_ast_path, mapping_requirements_path) -> TestgenModel:
    """Both artifacts into one model — the loading step of the pipeline."""
    model = TestgenModel()
    load_mapping_ast(mapping_ast_path, model)
    load_mapping_requirements(mapping_requirements_path, model)
    return model


def source_slice(codebase_root, function) -> str:
    """The exact definition text of *function*, sliced by byte offsets.

    Byte slicing — not line slicing — is the correct primitive, and the
    semantics are stage 2's: ``start_byte:end_byte`` against the codebase
    file's bytes, decoded UTF-8, so the result compares as text. Stage 1's
    columns are byte offsets that disagree with character indices on
    non-ASCII lines; never slice by them.
    """
    path = Path(codebase_root) / function.file_path
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(
            f"cannot read source for {function.unit_id}: {path}: "
            f"{exc.strerror or exc}"
        ) from exc
    start, end = function.start_byte, function.end_byte
    if not 0 <= start <= end <= len(data):
        raise InputError(
            f"byte span {start}:{end} of {function.unit_id} is outside {path} "
            f"({len(data)} bytes) — the codebase may have changed since it was "
            f"parsed"
        )
    return data[start:end].decode("utf-8")
