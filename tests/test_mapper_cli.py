"""The mapper CLI's argument parsing and input validation."""

from pathlib import Path

from meridian_mapper.cli import EXIT_CANNOT_RUN, build_parser, main, resolve_codebase

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
AST_JSON = FIXTURES / "ast.json"
CODEBASE = FIXTURES / "codebase"


def a_requirements_doc(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("1. Something\n", encoding="utf-8")
    return path


def test_out_defaults_to_mapping_ast_json():
    args = build_parser().parse_args(["a.json", "r.md", "root"])
    assert args.out == Path("mapping_ast.json")
    assert resolve_codebase(args) == Path("root")


def test_codebase_flag_is_accepted_instead_of_the_positional():
    args = build_parser().parse_args(["a.json", "r.md", "--codebase", "root"])
    assert resolve_codebase(args) == Path("root")


def test_missing_ast_json_exits_two(tmp_path, capsys):
    code = main([str(tmp_path / "nope.json"),
                 str(a_requirements_doc(tmp_path)), str(CODEBASE)])
    assert code == EXIT_CANNOT_RUN
    assert "ast.json not found" in capsys.readouterr().err


def test_missing_requirements_doc_exits_two(tmp_path, capsys):
    code = main([str(AST_JSON), str(tmp_path / "nope.md"), str(CODEBASE)])
    assert code == EXIT_CANNOT_RUN
    assert "requirements document not found" in capsys.readouterr().err


def test_missing_codebase_root_exits_two(tmp_path, capsys):
    code = main([str(AST_JSON), str(a_requirements_doc(tmp_path))])
    assert code == EXIT_CANNOT_RUN
    assert "no codebase root given" in capsys.readouterr().err


def test_bad_schema_version_exits_two(tmp_path, capsys):
    code = main([str(FIXTURES / "ast_schema_v1.json"),
                 str(a_requirements_doc(tmp_path)), str(CODEBASE)])
    assert code == EXIT_CANNOT_RUN
    assert "schema_version" in capsys.readouterr().err


def test_negative_threshold_exits_two(tmp_path, capsys):
    code = main([str(AST_JSON), str(a_requirements_doc(tmp_path)), str(CODEBASE),
                 "--category-leak-threshold", "-1"])
    assert code == EXIT_CANNOT_RUN
    assert "--category-leak-threshold cannot be negative" in capsys.readouterr().err


def test_malformed_requirements_document_exits_two(tmp_path, capsys):
    code = main([str(AST_JSON), str(FIXTURES / "requirements_malformed.md"),
                 str(CODEBASE), "--backend", "scripted_fake"])
    assert code == EXIT_CANNOT_RUN
    assert "error:" in capsys.readouterr().err
