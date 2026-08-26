"""The mapper, end to end through its real CLI entry point (chunk 6).

One fixture codebase and one requirements document are driven through
``cli.main`` with the scripted fake injected — no network call, no money spent
(D14) — and both artifact files are asserted, along with all three exit codes
(D21) and D20's rule that Artifact 2 carries no diagnostics anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from meridian_mapper.artifacts import ARTIFACT_REQUIREMENTS, ARTIFACT_TWO_NAME
from meridian_mapper.cli import EXIT_CANNOT_RUN, EXIT_EXHAUSTED, EXIT_OK, main
from meridian_mapper.llm import ScriptedFakeLLM, ScriptedScript
from meridian_mapper.model import TIER_DETERMINISTIC, TIER_LLM_ASSERTED

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
CODEBASE = FIXTURES / "codebase"
AST_JSON = FIXTURES / "ast.json"
REQ_DOC = FIXTURES / "requirements_wellformed.md"

ADD_ITEM = "6ef3dca1dc5d"
TOTAL_PRICE = "129e61f608e7"
SUMMARISE = "a4aab26adc36"
CALCULER = "4c2f7c64368b"
RESUME = "3c2c45288855"

GOOD_ADD_ITEM = "cart[item] = cart.get(item, 0) + quantity"
GOOD_TOTAL = "return sum"
BAD_EVIDENCE = "raise ValueError('never written in this codebase')"


def _fake(claims=None, mappings=None):
    return ScriptedFakeLLM(ScriptedScript(
        mappings=mappings if mappings is not None else {
            "1-1-1": [ADD_ITEM],
            "1-1-2": [TOTAL_PRICE],
            "1-2": [SUMMARISE, CALCULER],
            "2-1": [],
        },
        claims=claims if claims is not None else {
            ("1-1-1", ADD_ITEM): GOOD_ADD_ITEM,
            ("1-1-2", TOTAL_PRICE): GOOD_TOTAL,
        },
    ))


def _run(tmp_path, llm, extra=()):
    out = tmp_path / "mapping_ast.json"
    argv = [str(AST_JSON), str(REQ_DOC), str(CODEBASE), "--out", str(out),
            "--category-leak-threshold", "1", *extra]
    return main(argv, llm=llm), out


def _load(out):
    one = json.loads(out.read_text(encoding="utf-8"))
    two = json.loads((out.parent / ARTIFACT_TWO_NAME).read_text(encoding="utf-8"))
    return one, two


def _flatten(nodes):
    """Every requirement node of Artifact 2, in document order."""
    for node in nodes:
        yield node
        yield from _flatten(node["children"])


def _walk_json(value):
    """Every key of every object anywhere in *value*."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


# --- exit code 0: a clean run --------------------------------------------


def test_clean_run_exits_zero_and_writes_both_artifacts(tmp_path):
    code, out = _run(tmp_path, _fake())
    assert code == EXIT_OK

    one, two = _load(out)
    assert one["artifact"] == "mapping_ast"
    assert two["artifact"] == ARTIFACT_REQUIREMENTS
    assert (out.parent / ARTIFACT_TWO_NAME).is_file()


def test_artifact_two_follows_the_out_path(tmp_path):
    nested = tmp_path / "results"
    nested.mkdir()
    out = nested / "custom_name.json"
    code = main([str(AST_JSON), str(REQ_DOC), str(CODEBASE), "--out", str(out),
                 "--category-leak-threshold", "1"], llm=_fake())

    assert code == EXIT_OK
    assert out.is_file()
    # D10: the name is fixed, the directory follows --out.
    assert (nested / ARTIFACT_TWO_NAME).is_file()


def test_artifact_two_is_the_hierarchy_in_document_order(tmp_path):
    _, out = _run(tmp_path, _fake())
    _, two = _load(out)

    assert [n["code"] for n in _flatten(two["requirements"])] == [
        "1", "1-1", "1-1-1", "1-1-2", "1-2", "2", "2-1",
    ]
    root = two["requirements"][0]
    assert root["text"].startswith("Cart management")
    assert root["is_category"] is True


def test_category_requirements_carry_no_code_blocks(tmp_path):
    _, out = _run(tmp_path, _fake())
    _, two = _load(out)

    for node in _flatten(two["requirements"]):
        if node["is_category"]:
            assert node["code_blocks"] == []


def test_leaf_code_blocks_describe_signature_file_and_line_range(tmp_path):
    _, out = _run(tmp_path, _fake())
    _, two = _load(out)
    nodes = {n["code"]: n for n in _flatten(two["requirements"])}

    blocks = nodes["1-1-1"]["code_blocks"]
    assert len(blocks) == 1
    assert blocks[0]["signature"] == "def add_item(cart, item, quantity=1)"
    assert blocks[0]["file_path"] == "shop/cart.py"
    assert (blocks[0]["line_number"], blocks[0]["end_line"]) == (4, 7)


def test_empty_leaf_appears_with_an_empty_list(tmp_path):
    _, out = _run(tmp_path, _fake())
    _, two = _load(out)
    nodes = {n["code"]: n for n in _flatten(two["requirements"])}

    # D17: mapped to nothing is a result, and it is still in the output.
    assert nodes["2-1"]["is_category"] is False
    assert nodes["2-1"]["code_blocks"] == []


def test_category_leak_flag_is_visible_in_artifact_two(tmp_path):
    _, out = _run(tmp_path, _fake())
    _, two = _load(out)
    nodes = {n["code"]: n for n in _flatten(two["requirements"])}

    assert nodes["1-2"]["category_leak"] is True
    assert {b["unit_id"] for b in nodes["1-2"]["code_blocks"]} == {
        SUMMARISE, CALCULER,
    }
    assert nodes["1-1-1"]["category_leak"] is False


def test_the_two_artifacts_agree_with_each_other(tmp_path):
    _, out = _run(tmp_path, _fake())
    one, two = _load(out)

    from_two = {}
    for node in _flatten(two["requirements"]):
        for block in node["code_blocks"]:
            from_two.setdefault(block["unit_id"], []).append(node["code"])
    from_one = {
        unit["unit_id"]: unit["requirement_codes"]
        for unit in one["units"] if unit["requirement_codes"]
    }
    assert from_two == from_one

    tiers = {t for unit in one["units"] for t in unit["verification"].values()}
    assert tiers == {TIER_DETERMINISTIC, TIER_LLM_ASSERTED}


# --- exit code 1: verification exhausted ---------------------------------


def test_exhaustion_exits_one_with_both_artifacts_written(tmp_path):
    llm = _fake(claims={
        ("1-1-1", ADD_ITEM): GOOD_ADD_ITEM,
        ("1-1-2", TOTAL_PRICE): BAD_EVIDENCE,
    })
    code, out = _run(tmp_path, llm)

    assert code == EXIT_EXHAUSTED
    one, two = _load(out)

    # The outputs are written and valid — the exit code points at the notes.
    unit = {u["unit_id"]: u for u in one["units"]}[TOTAL_PRICE]
    assert unit["requirement_codes"] == []
    assert unit["structural_test_only"] is True
    assert len(unit["error_notes"]) == 1
    assert unit["error_notes"][0]["requirement_code"] == "1-1-2"

    # And Artifact 2 simply no longer lists it under that requirement.
    nodes = {n["code"]: n for n in _flatten(two["requirements"])}
    assert nodes["1-1-2"]["code_blocks"] == []


def test_artifact_two_carries_no_error_notes_anywhere(tmp_path):
    """D20: the requirements view feeds the GUI highlighter, nothing else."""
    llm = _fake(claims={
        ("1-1-1", ADD_ITEM): GOOD_ADD_ITEM,
        ("1-1-2", TOTAL_PRICE): BAD_EVIDENCE,
    })
    code, out = _run(tmp_path, llm)
    assert code == EXIT_EXHAUSTED

    _, two = _load(out)
    keys = set(_walk_json(two["requirements"]))
    assert "error_notes" not in keys
    assert "attempts" not in keys
    assert "structural_test_only" not in keys
    assert "verification" not in keys
    assert BAD_EVIDENCE not in (out.parent / ARTIFACT_TWO_NAME).read_text(
        encoding="utf-8"
    )


# --- exit code 2: could not start ----------------------------------------


def test_unreadable_output_directory_exits_two(tmp_path, capsys):
    out = tmp_path / "no_such_dir" / "mapping_ast.json"
    code = main([str(AST_JSON), str(REQ_DOC), str(CODEBASE), "--out", str(out)],
                llm=_fake())

    assert code == EXIT_CANNOT_RUN
    assert "does not exist" in capsys.readouterr().err


def test_missing_input_exits_two(tmp_path, capsys):
    code = main([str(tmp_path / "nope.json"), str(REQ_DOC), str(CODEBASE)],
                llm=_fake())
    assert code == EXIT_CANNOT_RUN
    assert "ast.json not found" in capsys.readouterr().err


# --- the CLI's own surface -----------------------------------------------


def test_help_documents_every_flag(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--help"])
    text = capsys.readouterr().out
    for flag in ("--out", "--codebase", "--requirements-format", "--backend",
                 "--model", "--claude-binary", "--llm-timeout",
                 "--category-leak-threshold", "--max-retries", "--version"):
        assert flag in text
