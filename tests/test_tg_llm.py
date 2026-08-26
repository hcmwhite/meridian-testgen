"""The LLM interface, the scripted fake, the backend, and the prompt log (D31).

Every test here runs against the scripted fake or against canned CLI output.
Nothing in this file may reach the network or spend money: the real ``claude``
binary is never invoked, and the backend is only ever exercised through its
``runner`` seam.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from meridian_testgen.claude_cli import (
    ClaudeCliLLM,
    build_generation_prompt,
    parse_cli_envelope,
    parse_cli_response,
    payload_from_envelope,
)
from meridian_testgen.llm import (
    BACKEND_CLAUDE_CLI,
    BACKEND_SCRIPTED_FAKE,
    GeneratedTest,
    GenerationItem,
    LLMConfig,
    LLMError,
    LLMUsage,
    ScriptedFakeLLM,
    ScriptedScript,
    create_llm,
)
from meridian_testgen.model import STRUCTURAL_MARKER, TIER_DETERMINISTIC
from meridian_testgen.promptlog import HEADER_PREFIX, PromptLog


def item(unit_id="pkg/mod.py::f", code="1-1", **kwargs):
    fields = dict(
        unit_id=unit_id,
        requirement_code=code,
        dotted_name="mod.f",
        signature="f(count: int) -> str",
        file_path="pkg/mod.py",
        line_number=3,
        end_line=5,
        source="def f(count: int) -> str:\n    return str(count)\n",
        requirement_text="The system renders a count as text.",
        obligations=("parameter 'count' (int) — exercise a representative value",),
    )
    fields.update(kwargs)
    return GenerationItem(**fields)


def envelope(payload, usage=None, cost=None, **extra):
    body = {"result": json.dumps(payload)}
    if usage is not None:
        body["usage"] = usage
    if cost is not None:
        body["total_cost_usd"] = cost
    body.update(extra)
    return json.dumps(body)


def answers(*entries):
    return {"tests": [
        {"unit_id": u, "requirement": r, "source": s} for u, r, s in entries
    ]}


# --- the fake and the interface ------------------------------------------

def test_fake_answers_a_single_item_batch():
    one = item()
    llm = ScriptedFakeLLM(ScriptedScript(tests={one.key: "def test_one(): pass"}))
    results = llm.generate_tests([one])
    assert [r.key for r in results] == [one.key]
    assert results[0].source == "def test_one(): pass"
    assert llm.calls == [[one.key]]


def test_fake_answers_a_multi_item_batch_in_one_call():
    batch = [item(code="1-1"), item(code="1-2"), item(unit_id="pkg/mod.py::g",
                                                      code=STRUCTURAL_MARKER)]
    llm = ScriptedFakeLLM()
    results = llm.generate_tests(batch)
    assert [r.key for r in results] == [i.key for i in batch]
    # One batch is one call (D28), not one call per item.
    assert llm.calls == [[i.key for i in batch]]


def test_fake_consumes_a_list_one_entry_per_call():
    one = item()
    llm = ScriptedFakeLLM(ScriptedScript(tests={one.key: ["", "bad(", "def test_ok(): pass"]}))
    assert llm.generate_tests([one])[0].source == ""
    assert llm.generate_tests([one])[0].source == "bad("
    assert llm.generate_tests([one])[0].source == "def test_ok(): pass"
    with pytest.raises(LLMError):
        llm.generate_tests([one])


def test_fake_raises_a_scripted_exception():
    one = item()
    llm = ScriptedFakeLLM(ScriptedScript(tests={one.key: LLMError("model is down")}))
    with pytest.raises(LLMError, match="model is down"):
        llm.generate_tests([one])


def test_fake_can_omit_an_item_from_its_answer():
    a, b = item(code="1-1"), item(code="1-2")
    llm = ScriptedFakeLLM(ScriptedScript(tests={a.key: None}))
    assert [r.key for r in llm.generate_tests([a, b])] == [b.key]


def test_a_result_for_an_unlisted_item_is_dropped_with_a_warning(caplog):
    one = item()
    stray = GeneratedTest("other/mod.py::z", "9-9", "def test_stray(): pass")
    llm = ScriptedFakeLLM(ScriptedScript(extra=[stray]))
    with caplog.at_level("WARNING", logger="meridian_testgen.llm"):
        results = llm.generate_tests([one])
    assert [r.key for r in results] == [one.key]
    assert "not in this batch" in caplog.text


def test_a_repeated_identity_in_one_answer_is_merged_not_dropped():
    """Several entries for one item are the model splitting its test cases —
    merging keeps them all in one source (dropping them lost four of five
    real tests on the first live run, 2026-08-23)."""
    one = item()
    duplicate = GeneratedTest(one.unit_id, one.requirement_code, "def test_second(): pass")
    llm = ScriptedFakeLLM(ScriptedScript(tests={one.key: "def test_first(): pass"},
                                         extra=[duplicate]))
    results = llm.generate_tests([one])
    assert len(results) == 1
    assert "def test_first(): pass" in results[0].source
    assert "def test_second(): pass" in results[0].source
    assert results[0].key == one.key


def test_an_empty_batch_never_reaches_the_backend():
    llm = ScriptedFakeLLM()
    assert llm.generate_tests([]) == []
    assert llm.calls == []


def test_the_fake_records_the_items_and_their_failure_reasons():
    first = item()
    retry = first.with_failure("did not compile: unexpected EOF")
    llm = ScriptedFakeLLM()
    llm.generate_tests([first])
    llm.generate_tests([retry])
    assert [i.prior_failure for call in llm.items for i in call] == [
        None, "did not compile: unexpected EOF",
    ]
    assert first.prior_failure is None  # with_failure does not mutate


def test_unscripted_default_source_carries_the_traceability_comment():
    one = item()
    source = ScriptedFakeLLM().generate_tests([one])[0].source
    assert f"# meridian: unit_id={one.unit_id} requirement=1-1" in source
    compile(source, "<generated>", "exec")


# --- usage accounting -----------------------------------------------------

def test_usage_starts_empty_and_serializes():
    assert LLMUsage().as_dict() == {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "total_cost_usd": 0.0,
    }


def test_usage_accumulates_across_canned_envelopes():
    one, two = item(code="1-1"), item(code="1-2")
    stdout = [
        envelope(answers((one.unit_id, "1-1", "def test_a(): pass")),
                 usage={"input_tokens": 100, "output_tokens": 20,
                        "cache_read_input_tokens": 7},
                 cost=0.01),
        envelope(answers((two.unit_id, "1-2", "def test_b(): pass")),
                 usage={"input_tokens": 50, "output_tokens": 5}, cost=0.02),
    ]
    llm = ClaudeCliLLM(runner=lambda command: stdout.pop(0))
    llm.generate_tests([one])
    llm.generate_tests([two])
    assert llm.usage.as_dict() == {
        "calls": 2, "input_tokens": 150, "output_tokens": 25,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 7,
        "total_cost_usd": 0.03,
    }


def test_an_envelope_without_usage_still_counts_the_call():
    one = item()
    llm = ClaudeCliLLM(runner=lambda command: envelope(
        answers((one.unit_id, "1-1", "def test_a(): pass"))))
    llm.generate_tests([one])
    assert llm.usage.calls == 1
    assert llm.usage.input_tokens == 0


def test_a_malformed_payload_still_books_its_tokens():
    one = item()
    llm = ClaudeCliLLM(runner=lambda command: envelope(
        {"nothing": "useful"}, usage={"input_tokens": 11}, cost=0.5))
    with pytest.raises(LLMError):
        llm.generate_tests([one])
    assert llm.usage.calls == 1
    assert llm.usage.input_tokens == 11


# --- canned-envelope parsing ---------------------------------------------

def test_parse_cli_response_unwraps_the_envelope_and_a_fence():
    stdout = json.dumps({"result": '```json\n{"tests": []}\n```'})
    assert parse_cli_response(stdout) == {"tests": []}


@pytest.mark.parametrize("stdout, fragment", [
    ("not json at all", "did not print JSON"),
    (json.dumps({"nope": 1}), "no 'result' field"),
    (json.dumps({"result": "boom", "is_error": True}), "reported an error"),
    (json.dumps({"result": 17}), "not text"),
    (json.dumps({"result": "sorry, I cannot"}), "not the JSON object"),
    (json.dumps({"result": "[1, 2]"}), "not a JSON object"),
])
def test_canned_envelope_parse_failures_are_llm_errors(stdout, fragment):
    with pytest.raises(LLMError, match=fragment):
        parse_cli_response(stdout)


@pytest.mark.parametrize("payload, fragment", [
    ({"tests": "not a list"}, "without a 'tests' list"),
    ({"tests": ["not an object"]}, "not an object"),
    ({"tests": [{"unit_id": "x"}]}, "missing string"),
])
def test_a_bad_answers_is_an_llm_error(payload, fragment):
    llm = ClaudeCliLLM(runner=lambda command: envelope(payload))
    with pytest.raises(LLMError, match=fragment):
        llm.generate_tests([item()])


def test_payload_from_envelope_needs_the_result_key():
    with pytest.raises(KeyError):
        payload_from_envelope({})
    assert parse_cli_envelope(json.dumps({"result": "{}"}))["result"] == "{}"


# --- the real backend's deterministic halves ------------------------------

def test_build_command_is_read_only_and_scoped_to_the_codebase(tmp_path):
    llm = ClaudeCliLLM(codebase_root=tmp_path, model="a-model", binary="claude")
    command = llm.build_command("PROMPT")
    assert command[:5] == ["claude", "-p", "PROMPT", "--output-format", "json"]
    assert "--model" in command and command[command.index("--model") + 1] == "a-model"
    assert command[command.index("--allowed-tools") + 1] == "Read,Grep,Glob"
    # "plan" made the CLI save a plan file instead of answering (2026-08-24).
    assert command[command.index("--permission-mode") + 1] == "default"
    assert command[command.index("--add-dir") + 1] == str(tmp_path)
    assert not any(flag.startswith("--dangerously") for flag in command)


def test_the_mapped_prompt_carries_d29s_ingredients():
    prompt = build_generation_prompt([item(
        tier=TIER_DETERMINISTIC, effect="renders the count",
        evidence="return str(count)")])
    assert "REQUIREMENT 1-1: The system renders a count as text." in prompt
    assert "def f(count: int) -> str:" in prompt
    assert "f(count: int) -> str" in prompt and "pkg/mod.py:3-5" in prompt
    assert "renders the count" in prompt and "return str(count)" in prompt
    assert "parameter 'count' (int)" in prompt
    assert "# meridian: unit_id=<unit_id> requirement=<requirement>" in prompt


def test_an_llm_asserted_pair_does_not_carry_the_unverified_claim():
    prompt = build_generation_prompt([item(
        tier="llm_asserted", effect="renders the count", evidence="return str(count)")])
    assert "stage-2 effect claim" not in prompt


def test_the_structural_prompt_drops_the_requirement_and_asks_for_context():
    prompt = build_generation_prompt([item(code=STRUCTURAL_MARKER,
                                           requirement_text="should not appear")])
    assert "should not appear" not in prompt
    assert "stage-2 effect claim" not in prompt
    assert "find this function's callers" in prompt
    assert f"requirement: {STRUCTURAL_MARKER}" in prompt


def test_a_batch_prompt_lists_every_item_once():
    prompt = build_generation_prompt([item(code="1-1"), item(code="1-2")])
    assert "GENERATION ITEMS (2)" in prompt
    assert "ITEM 1" in prompt and "ITEM 2" in prompt


def test_a_retry_prompt_carries_that_items_own_failure_reason():
    a = item(code="1-1").with_failure("collect-only failed: NameError")
    b = item(code="1-2")
    prompt = build_generation_prompt([a, b])
    assert "collect-only failed: NameError" in prompt
    assert prompt.count("previously") == 0
    assert prompt.count("A previous attempt at this item was rejected") == 1


def test_the_backend_returns_the_answers_it_was_given():
    one, two = item(code="1-1"), item(code="1-2")
    llm = ClaudeCliLLM(runner=lambda command: envelope(answers(
        (one.unit_id, "1-1", "def test_a(): pass"),
        (two.unit_id, "1-2", "def test_b(): pass"),
    )))
    assert [r.key for r in llm.generate_tests([one, two])] == [one.key, two.key]


def test_a_missing_binary_is_an_llm_error():
    # The one place a real subprocess is attempted, and it is a name that
    # cannot exist — no test in this repository runs the real claude CLI.
    real = ClaudeCliLLM(binary="definitely-not-a-real-binary-xyz")
    with pytest.raises(LLMError, match="cannot run"):
        real.generate_tests([item()])


# --- backend selection ----------------------------------------------------

def test_create_llm_selects_by_config_value(tmp_path):
    fake = create_llm(LLMConfig(backend=BACKEND_SCRIPTED_FAKE))
    assert isinstance(fake, ScriptedFakeLLM)
    real = create_llm(LLMConfig(backend=BACKEND_CLAUDE_CLI, model="m"),
                      codebase_root=tmp_path)
    assert isinstance(real, ClaudeCliLLM)
    assert real.model == "m" and real.codebase_root == tmp_path


def test_an_unknown_backend_is_an_llm_error():
    with pytest.raises(LLMError, match="unknown llm backend"):
        create_llm(LLMConfig(backend="telepathy"))


# --- the prompt log -------------------------------------------------------

class FixedClock:
    """Ticks one minute per reading, so headers are visibly per-prompt."""

    def __init__(self):
        self.moment = datetime(2026, 8, 23, 9, 30, tzinfo=timezone.utc)

    def __call__(self):
        moment = self.moment
        self.moment += timedelta(minutes=1)
        return moment


def test_prompt_debug_writes_one_timestamped_header_per_prompt(tmp_path):
    log = PromptLog(tmp_path, clock=FixedClock())
    llm = create_llm(LLMConfig(backend=BACKEND_SCRIPTED_FAKE), prompt_log=log)
    llm.generate_tests([item(code="1-1")])
    llm.generate_tests([item(code="1-2"), item(code="1-3")])

    written = list(tmp_path.glob("prompts-testgen-*.log"))
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    headers = [line for line in text.splitlines() if line.startswith(HEADER_PREFIX)]
    assert headers == [
        "=== prompt 1 2026-08-23T09:31:00Z ===",
        "=== prompt 2 2026-08-23T09:32:00Z ===",
    ]
    # Two calls, two records — the second is the two-item batch's one prompt.
    assert text.count("GENERATION ITEMS (1)") == 1
    assert text.count("GENERATION ITEMS (2)") == 1
    assert "REQUIREMENT 1-3" in text


def test_the_real_backend_logs_its_prompts_too(tmp_path):
    one = item()
    llm = create_llm(LLMConfig(backend=BACKEND_CLAUDE_CLI), codebase_root=tmp_path,
                     prompt_log=PromptLog(tmp_path, clock=FixedClock()))
    llm._runner = lambda command: envelope(
        answers((one.unit_id, "1-1", "def test_a(): pass")))
    llm.generate_tests([one])
    written = list(tmp_path.glob("prompts-testgen-*.log"))
    assert len(written) == 1
    assert "GENERATION ITEMS (1)" in written[0].read_text(encoding="utf-8")


def test_without_prompt_debug_no_file_is_written(tmp_path):
    llm = create_llm(LLMConfig(backend=BACKEND_SCRIPTED_FAKE))
    assert llm.prompt_log is None
    llm.generate_tests([item()])
    assert list(tmp_path.iterdir()) == []


def test_an_unused_prompt_log_leaves_no_empty_file(tmp_path):
    PromptLog(tmp_path, clock=FixedClock())
    assert list(tmp_path.iterdir()) == []


def test_prompt_names_the_import_the_conftest_supports():
    prompt = build_generation_prompt([item()])
    assert "from mod import" in prompt
    assert "conftest" in prompt


def test_prompt_forbids_real_external_resources():
    prompt = build_generation_prompt([item()])
    assert "never touch real external resources" in prompt
    assert "unittest.mock BEFORE importing" in prompt
