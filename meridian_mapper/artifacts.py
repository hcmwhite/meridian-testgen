"""The two artifact writers: both render from the one in-memory model (D11).

**Artifact 1** is the annotated AST list: one record per ast function, in the
input file's order, carrying the stage-1 fields verbatim plus what the mapper
learned — the requirement codes the function satisfies, the verification tier
per assignment, the ``structural_test_only`` tag, and any error notes from
failed verification retries (D20: error notes live here and only here).

It is written to the ``--out`` path, default ``mapping_ast.json`` (D10).

**Artifact 2** is the requirements-first view of the same run: the hierarchy
in document order, each requirement with the code blocks that satisfy it. It
is written as ``mapping_requirements.json`` beside the resolved ``--out``
path (D10) and carries no error notes at all (D20).

Neither writer re-reads an input file or re-derives anything the model already
holds: they are two rendering passes over one structure, not two pipelines.

**On the envelope.** The file opens with a run-metadata header in the stage-1
style, then streams the records under a ``units`` key, so a consumer that can
read ``ast.json`` can read this. The writing is a local twenty-line copy of
that pattern rather than an import of
``meridian_parser.writer``: D8 keeps stage 2 from importing stage-1 internals
at all, and the two stages meeting only through file formats is the point of
the separation. The cost is that the pattern exists twice; the benefit is that
neither stage can break the other by refactoring.
"""

from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone

from meridian_mapper import __version__

# The mapper's own output schema, independent of stage 1's.
ARTIFACT_SCHEMA_VERSION = 1

ARTIFACT_AST = "mapping_ast"


class ArtifactError(Exception):
    """The artifact could not be written."""


def run_metadata(artifact: str, ast_json, requirements_doc, codebase_root,
                 source_meta=None) -> dict:
    """The header describing this mapping run.

    Small on purpose, and in stage 1's shape: which tool, when, and over which
    three inputs. *source_meta* carries the stage-1 envelope of the ``ast.json``
    that was read, so a record can be traced back to the parser run that
    produced its universe.
    """
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact": artifact,
        "tool": f"meridian-mapper {__version__}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ast_json": str(os.fspath(ast_json)) if ast_json is not None else None,
        "requirements_doc": (
            str(os.fspath(requirements_doc)) if requirements_doc is not None else None
        ),
        "codebase": (
            str(os.fspath(codebase_root)) if codebase_root is not None else None
        ),
        "source_run": dict(source_meta or {}),
        "python": platform.python_version(),
    }


def annotated_record(function) -> dict:
    """One Artifact 1 record: the stage-1 fields, then the mapper's.

    The stage-1 fields are re-emitted verbatim and first, so the record reads
    as the original unit with annotations appended. The mapper's own keys are
    always present — an unmapped function carries an empty code list, not a
    missing one — because a consumer should never have to tell "no
    requirements" apart from "this field was not written".
    """
    annotation = function.annotation
    record = dict(function.record)
    record["requirement_codes"] = list(annotation.requirement_codes)
    record["verification"] = {
        code: annotation.tiers.get(code)
        for code in annotation.requirement_codes
    }
    record["claims"] = {
        code: dict(claim) for code, claim in annotation.claims.items()
    }
    record["structural_test_only"] = bool(annotation.structural_test_only)
    record["error_notes"] = [
        {"requirement_code": note.requirement_code,
         "attempts": [dict(attempt) for attempt in note.attempts]}
        for note in annotation.error_notes
    ]
    return record


def write_artifact_one(model, out_path, ast_json=None, requirements_doc=None,
                       codebase_root=None, llm_usage=None) -> int:
    """Write Artifact 1 for *model* to *out_path*. Returns the record count.

    *llm_usage* is the run's LLM accounting (an ``LLMUsage.as_dict()``); when
    given, it lands in the metadata header as ``llm_usage``, so a mapping file
    carries its own price. Diagnostic like the error notes, so Artifact 1
    only (D20).
    """
    meta = run_metadata(
        ARTIFACT_AST, ast_json, requirements_doc, codebase_root,
        model.source_meta,
    )
    if llm_usage:
        meta["llm_usage"] = dict(llm_usage)
    records = [annotated_record(f) for f in model.ordered_functions()]
    _write_enveloped(out_path, meta, records)
    return len(records)


def _write_enveloped(path, meta: dict, records: list, array_key: str = "units") -> None:
    """Stream *records* under *array_key* beneath *meta*'s fields.

    The same file layout stage 1 writes: metadata fields first, then the array,
    one record per line so a diff between two runs is readable.
    """
    path = os.fspath(path)
    try:
        handle = open(path, "w", encoding="utf-8")
    except OSError as exc:
        directory = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(directory):
            raise ArtifactError(
                f"cannot write {path}: directory {directory} does not exist"
            ) from exc
        raise ArtifactError(f"cannot write {path}: {exc.strerror or exc}") from exc
    try:
        handle.write("{\n")
        for key, value in meta.items():
            handle.write(f"  {json.dumps(key)}: {json.dumps(value)},\n")
        handle.write(f"  {json.dumps(array_key)}: [")
        for index, record in enumerate(records):
            handle.write("," if index else "")
            handle.write("\n    " + json.dumps(record, sort_keys=False))
        handle.write("\n  ]" if records else "]")
        handle.write("\n}\n")
    except OSError as exc:
        raise ArtifactError(f"cannot write {path}: {exc.strerror or exc}") from exc
    finally:
        handle.close()


# --- Artifact 2: the requirements-first view (chunk 6) ---------------------
#
# The same model, rendered the other way round: the requirements hierarchy in
# document order, each node carrying the code blocks that satisfy it. It feeds
# the GUI highlighter, so a "code block" is exactly what a highlighter needs —
# signature, filename, line range — and nothing diagnostic. D20 is explicit:
# error notes live in Artifact 1 and only there, so no field below carries
# one, not even indirectly.

ARTIFACT_REQUIREMENTS = "mapping_requirements"

# D10: the name is fixed, and the file lands beside the resolved --out path.
ARTIFACT_TWO_NAME = "mapping_requirements.json"


def code_block(function) -> dict:
    """One mapped function as the highlighter sees it.

    Signature, filename and line range — a *reference* into the codebase, not
    its contents, and not the mapper's diagnostics.
    """
    record = function.record
    return {
        "unit_id": function.unit_id,
        "dotted_name": record.get("dotted_name", ""),
        "signature": record.get("signature", ""),
        "file_path": record.get("file_path", ""),
        "line_number": record.get("line_number", 0),
        "end_line": record.get("end_line", 0),
    }


def requirement_node(model, requirement) -> dict:
    """One requirement, with its children, in document order.

    A category node carries no code blocks — it is never mapped (D13) — and a
    leaf that mapped to nothing carries an empty list rather than a missing
    key (D17): "no code satisfies this" and "this was never asked" must not
    look the same to a reader.
    """
    blocks = [
        code_block(model.functions[unit_id])
        for unit_id in requirement.mapped_unit_ids
        if unit_id in model.functions
    ]
    return {
        "code": requirement.code,
        "text": requirement.text,
        "is_category": bool(requirement.is_category),
        "category_leak": bool(requirement.category_leak),
        "code_blocks": [] if requirement.is_category else blocks,
        "children": [
            requirement_node(model, child) for child in requirement.children
        ],
    }


def artifact_two_path(out_path):
    """``mapping_requirements.json`` beside the resolved Artifact 1 path (D10)."""
    directory = os.path.dirname(os.path.abspath(os.fspath(out_path)))
    return os.path.join(directory, ARTIFACT_TWO_NAME)


def write_artifact_two(model, out_path, ast_json=None, requirements_doc=None,
                       codebase_root=None) -> int:
    """Write Artifact 2 beside *out_path*. Returns the top-level node count.

    *out_path* is Artifact 1's path: this writer derives its own name from it
    (D10) rather than being told, so the two files cannot drift apart.
    """
    meta = run_metadata(
        ARTIFACT_REQUIREMENTS, ast_json, requirements_doc, codebase_root,
        model.source_meta,
    )
    nodes = [requirement_node(model, node) for node in model.requirements]
    _write_enveloped(artifact_two_path(out_path), meta, nodes,
                     array_key="requirements")
    return len(nodes)
