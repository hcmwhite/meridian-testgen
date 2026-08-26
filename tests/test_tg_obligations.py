"""The deterministic structural-obligation checklist (D33).

Every test here reads a source string and asserts on the strings that come
back. There is no LLM anywhere in this pass and none of these tests may need
one: if a checklist entry cannot be justified by pointing at the source, it
does not belong in the checklist.
"""

from pathlib import Path

import pytest

from meridian_testgen.inputs import load_model, source_slice
from meridian_testgen.obligations import (
    ObligationError,
    obligations_for_function,
    obligations_for_source,
)

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"


def kinds(lines, prefix):
    return [line for line in lines if line.startswith(prefix)]


def test_typed_parameter_names_its_hint():
    lines = obligations_for_source("def f(count: int) -> str:\n    return str(count)\n")
    assert "parameter 'count' (int) — exercise a representative value" in lines


def test_untyped_parameter_asks_for_a_wrong_type_value():
    lines = obligations_for_source("def f(count):\n    return count\n")
    assert (
        "parameter 'count' — untyped — exercise a representative and a "
        "wrong-type value" in lines
    )


def test_self_and_cls_are_not_parameters_a_test_varies():
    method = obligations_for_source("def m(self, value):\n    return value\n")
    assert not [line for line in method if line.startswith("parameter 'self'")]
    classmethod_ = obligations_for_source("def m(cls, value):\n    return value\n")
    assert not [line for line in classmethod_ if line.startswith("parameter 'cls'")]
    # A parameter merely *named* like one, in a later position, is still an input.
    plain = obligations_for_source("def f(value, self):\n    return self\n")
    assert kinds(plain, "parameter 'self'")


def test_varargs_and_keyword_arguments_are_parameters_too():
    lines = obligations_for_source(
        "def f(*args, flag: bool = False, **kwargs):\n    return flag\n"
    )
    assert kinds(lines, "parameter '*args'")
    assert kinds(lines, "parameter 'flag' (bool)")
    assert kinds(lines, "parameter '**kwargs'")


@pytest.mark.parametrize(
    "source",
    [
        "def f(value: int | None):\n    return value\n",
        "def f(value: Optional[int]):\n    return value\n",
        "def f(value: Union[int, None]):\n    return value\n",
    ],
)
def test_none_admitting_hints_get_a_none_obligation(source):
    lines = obligations_for_source(source)
    assert (
        "parameter 'value' — cover None (the hint admits None) and a present value"
        in lines
    )


def test_a_none_default_gets_a_none_obligation_without_a_hint():
    lines = obligations_for_source("def f(value=None):\n    return value\n")
    assert (
        "parameter 'value' — cover None (default is None) and a present value" in lines
    )


def test_a_plain_hint_gets_no_none_obligation():
    lines = obligations_for_source("def f(value: int):\n    return value\n")
    assert not kinds(lines, "parameter 'value' — cover None")


def test_numeric_parameters_get_zero_one_many_boundaries():
    lines = obligations_for_source("def f(n: int) -> int:\n    return n\n")
    assert "parameter 'n' — cover the numeric boundaries: zero, one, many" in lines


def test_sequence_parameters_get_empty_one_many_boundaries():
    lines = obligations_for_source("def f(items: list) -> int:\n    return len(items)\n")
    assert (
        "parameter 'items' — cover the sequence boundaries: empty, one element, "
        "many elements" in lines
    )


def test_an_unclassified_hint_gets_no_boundary_obligation():
    lines = obligations_for_source("def f(when: datetime):\n    return when\n")
    assert not kinds(lines, "parameter 'when' — cover the")


def test_the_return_annotation_is_named_in_the_return_obligation():
    lines = obligations_for_source("def f() -> str:\n    return ''\n")
    assert "return — assert the result is str and has the expected value" in lines


def test_an_unannotated_return_still_gets_an_obligation():
    lines = obligations_for_source("def f():\n    pass\n")
    assert [line for line in lines if line.startswith("return — no annotation")]


def test_a_bare_function_still_gets_a_non_empty_checklist():
    # No parameters, no branches, no annotations — the return obligation alone
    # keeps the checklist from being empty, which is the point of D33.
    lines = obligations_for_source("def f():\n    return 1\n")
    assert len(lines) == 1
    assert lines[0].startswith("return — no annotation")


def test_every_branch_arm_gets_an_obligation_anchored_to_its_line():
    source = (
        "def f(n):\n"
        "    if n > 0:\n"
        "        return 1\n"
        "    elif n == 0:\n"
        "        return 0\n"
        "    else:\n"
        "        return -1\n"
    )
    lines = kinds(obligations_for_source(source, start_line=10), "cover ")
    assert lines == [
        "cover the if branch at line 11",
        "cover the if branch at line 13",
        "cover the else branch of the if at line 13",
    ]


def test_loops_and_their_else_arms_are_branches():
    source = (
        "def f(items):\n"
        "    for item in items:\n"
        "        print(item)\n"
        "    else:\n"
        "        pass\n"
        "    while items:\n"
        "        items.pop()\n"
    )
    lines = kinds(obligations_for_source(source), "cover ")
    assert lines == [
        "cover the loop body at line 2",
        "cover the else branch of the loop at line 2",
        "cover the loop body at line 6",
    ]


def test_try_arms_name_the_exception_each_handler_catches():
    source = (
        "def f():\n"
        "    try:\n"
        "        go()\n"
        "    except ValueError:\n"
        "        pass\n"
        "    except (KeyError, IndexError):\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
        "    finally:\n"
        "        pass\n"
    )
    lines = kinds(obligations_for_source(source), "cover ")
    assert lines == [
        "cover the try body at line 2",
        "cover the else branch of the try at line 2",
        "cover the finally block at line 2",
        "cover the except ValueError handler at line 4",
        "cover the except (KeyError, IndexError) handler at line 6",
        "cover the except any exception handler at line 8",
    ]


def test_match_arms_are_branches():
    source = (
        "def f(command):\n"
        "    match command:\n"
        "        case 'go':\n"
        "            return 1\n"
        "        case _:\n"
        "            return 0\n"
    )
    lines = kinds(obligations_for_source(source), "cover ")
    assert lines == [
        "cover the match arm ''go'' at line 3",
        "cover the match arm '_' at line 5",
    ]


def test_every_raise_gets_an_exception_obligation():
    source = (
        "def f(n):\n"
        "    if n < 0:\n"
        "        raise ValueError('negative')\n"
        "    raise NotImplementedError\n"
    )
    lines = kinds(obligations_for_source(source, start_line=100), "assert `")
    assert lines == [
        "assert `ValueError('negative')` is raised, from line 102",
        "assert `NotImplementedError` is raised, from line 103",
    ]


def test_a_nested_definitions_branches_belong_to_it_not_its_parent():
    source = (
        "def outer(flag):\n"
        "    def inner(x):\n"
        "        if x:\n"
        "            raise ValueError('inner')\n"
        "    return inner\n"
    )
    lines = obligations_for_source(source)
    assert not kinds(lines, "cover ")
    assert not kinds(lines, "assert `")


def test_a_method_slice_carrying_class_indentation_still_parses():
    # A method's byte slice starts at its `def` — column zero as text — while
    # its body keeps the class's indentation. That is a syntax error on its
    # own, and the checklist must survive it rather than blowing up.
    slice_ = "def m(self, values: list) -> int:\n" "        if values:\n" "            return len(values)\n" "        return 0\n"
    lines = obligations_for_source(slice_, start_line=7)
    assert kinds(lines, "parameter 'values' (list)")
    assert "cover the if branch at line 8" in lines


def test_source_that_is_not_a_definition_is_a_clear_error():
    with pytest.raises(ObligationError):
        obligations_for_source("x = 1\n")
    with pytest.raises(ObligationError):
        obligations_for_source("def f(:\n")


def _fixture_model():
    return load_model(
        FIXTURES / "mapping_ast.json", FIXTURES / "mapping_requirements.json"
    )


def test_the_full_checklist_for_a_fixture_function_is_pinned_and_deterministic():
    model = _fixture_model()
    codebase = FIXTURES / "codebase"
    function = model.functions["aaaa11112222"]
    body = source_slice(codebase, function)

    checklist = obligations_for_function(function, body)
    assert checklist == [
        "parameter 'price' — untyped — exercise a representative and a "
        "wrong-type value",
        "parameter 'percent' — untyped — exercise a representative and a "
        "wrong-type value",
        "return — no annotation — assert the returned value itself, "
        "including None where the function falls off its end",
        "cover the if branch at line 6",
        "assert `ValueError('percent out of range')` is raised, from line 7",
    ]
    # Determinism: the same input, twice, is the same list.
    assert obligations_for_function(function, body) == checklist


def test_every_fixture_function_gets_a_non_empty_checklist():
    model = _fixture_model()
    codebase = FIXTURES / "codebase"
    for function in model.ordered_functions():
        body = source_slice(codebase, function)
        assert obligations_for_function(function, body)
