"""Verification batching and the mapper's prompt log (chunk 6; D31, D32).

Every test drives :class:`ScriptedFakeLLM` against the committed fixture
codebase; nothing here calls a real model or the network (D14).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from meridian_mapper.astload import load_ast_json
from meridian_mapper.claude_cli import (
    ClaudeCliLLM,
    build_verify_batch_prompt,
    parse_batch_claims,
)
from meridian_mapper.llm import (
    Candidate,
    Claim,
    ScriptedFakeLLM,
    ScriptedScript,
    VerifyRequest,
)
from meridian_mapper.mapping import run_mapping
from meridian_mapper.model import TIER_DETERMINISTIC
from meridian_mapper.promptlog import HEADER_PREFIX, PromptLog
from meridian_mapper.requirements import load_into_model
from meridian_mapper.verification import (
    DEFAULT_BATCH_SIZE,
    VerificationConfig,
    run_verification,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
CODEBASE = FIXTURES / "codebase"

ADD_ITEM = "6ef3dca1dc5d"
TOTAL_PRICE = "129e61f608e7"
SUMMARISE = "a4aab26adc36"

EVIDENCE = {
    ADD_ITEM: "cart[item] = cart.get(item, 0) + quantity",
    TOTAL_PRICE: "return sum(prices[item] * count for item, count in cart.items())",
    SUMMARISE: 'return "\\n".join(f"{item} x{count}" for item, count in cart.items())',
}
BAD_EVIDENCE = "raise ValueError('never written in this codebase')"

THREE = [ADD_ITEM, TOTAL_PRICE, SUMMARISE]


def _mapped(claims, mapped_ids=THREE):
    """A model whose requirement 1-1-1 maps to *mapped_ids*, plus the fake."""
    model = load_ast_json(FIXTURES / "ast.json")
    load_into_model(model, FIXTURES / "requirements_wellformed.md")
    fake = ScriptedFakeLLM(
        ScriptedScript(mappings={"1-1-1": list(mapped_ids)}, claims=claims)
    )
    run_mapping(model, fake)
    return model, fake


def _all_good():
    return {("1-1-1", unit_id): EVIDENCE[unit_id] for unit_id in THREE}


def test_default_batch_size_is_one():
    assert DEFAULT_BATCH_SIZE == 1
    assert VerificationConfig().batch_size == 1


def test_batch_size_one_sends_each_pair_on_its_own():
    model, fake = _mapped(_all_good())

    summary = run_verification(model, fake, CODEBASE, VerificationConfig())

    assert summary.verified == 3
    assert summary.calls == 3
    assert fake.verify_batches == [
        [("1-1-1", ADD_ITEM)], [("1-1-1", TOTAL_PRICE)], [("1-1-1", SUMMARISE)],
    ]


def test_a_batch_of_three_verifies_in_one_call():
    model, fake = _mapped(_all_good())

    summary = run_verification(
        model, fake, CODEBASE, VerificationConfig(batch_size=3)
    )

    assert summary.verified == 3
    assert summary.pairs_checked == 3
    assert summary.calls == 1
    assert fake.verify_batches == [[("1-1-1", u) for u in THREE]]
    leaf = model.requirements[0].children[0].children[0]
    assert leaf.mapped_unit_ids == THREE
    for unit_id in THREE:
        assert model.functions[unit_id].annotation.tiers["1-1-1"] == (
            TIER_DETERMINISTIC
        )


def test_only_the_failed_pair_is_re_batched_with_its_own_reason():
    claims = _all_good()
    claims[("1-1-1", TOTAL_PRICE)] = [BAD_EVIDENCE, EVIDENCE[TOTAL_PRICE]]
    model, fake = _mapped(claims)

    summary = run_verification(
        model, fake, CODEBASE, VerificationConfig(batch_size=3)
    )

    assert summary.verified == 3
    assert summary.exhausted == 0
    assert summary.retries_used == 1
    assert summary.calls == 2
    # The retry carries the one failed pair, not the two that passed.
    assert fake.verify_batches == [
        [("1-1-1", u) for u in THREE], [("1-1-1", TOTAL_PRICE)],
    ]
    retry = [call for call in fake.verify_calls if call[1] == TOTAL_PRICE][-1]
    assert "does not appear" in retry[2]


def test_exhaustion_in_a_batch_still_writes_the_error_note():
    claims = _all_good()
    claims[("1-1-1", TOTAL_PRICE)] = BAD_EVIDENCE
    model, fake = _mapped(claims)

    summary = run_verification(
        model, fake, CODEBASE, VerificationConfig(batch_size=3)
    )

    assert summary.verified == 2
    assert summary.exhausted == 1
    # Three attempts for the failing pair, and the pairs that passed were not
    # dragged back into the retries (D18 is per pair, not per batch).
    assert [len(batch) for batch in fake.verify_batches] == [3, 1, 1]
    leaf = model.requirements[0].children[0].children[0]
    assert leaf.mapped_unit_ids == [ADD_ITEM, SUMMARISE]
    notes = model.functions[TOTAL_PRICE].annotation.error_notes
    assert len(notes) == 1
    assert notes[0].requirement_code == "1-1-1"
    assert [a["attempt"] for a in notes[0].attempts] == [1, 2, 3]
    assert all(a["reason"] for a in notes[0].attempts)


def test_a_claim_for_an_unlisted_pair_is_dropped(caplog):
    class Intruder(ScriptedFakeLLM):
        def _verify_claims(self, requests):
            requests = list(requests)
            self.verify_batches.append([r.key for r in requests])
            return [
                Claim("1-1-1", ADD_ITEM, "e", EVIDENCE[ADD_ITEM]),
                Claim("1-1-1", "not-a-unit", "e", "whatever"),
            ]

    model, _ = _mapped({}, mapped_ids=[ADD_ITEM])
    fake = Intruder(ScriptedScript())

    with caplog.at_level("WARNING"):
        summary = run_verification(
            model, fake, CODEBASE, VerificationConfig(batch_size=2)
        )

    assert summary.verified == 1
    assert "not in this batch" in caplog.text


def test_a_pair_the_batch_answer_skipped_fails_and_retries():
    class Partial(ScriptedFakeLLM):
        def _verify_claims(self, requests):
            requests = list(requests)
            self.verify_batches.append([r.key for r in requests])
            return [Claim("1-1-1", ADD_ITEM, "e", EVIDENCE[ADD_ITEM])]

    model, _ = _mapped({}, mapped_ids=[ADD_ITEM, TOTAL_PRICE])
    fake = Partial(ScriptedScript())

    summary = run_verification(
        model, fake, CODEBASE, VerificationConfig(batch_size=2)
    )

    assert summary.verified == 1
    assert summary.exhausted == 1
    notes = model.functions[TOTAL_PRICE].annotation.error_notes
    assert "no claim for this pair" in notes[0].attempts[0]["reason"]


# --- the batch prompt and its parsing (the deterministic backend halves) ---


def _candidate(unit_id):
    return Candidate(unit_id, "shop.cart.f", "f(x)", "shop/cart.py", 1, 2)


def test_batch_prompt_lists_every_pair_with_its_own_prior_failure():
    prompt = build_verify_batch_prompt([
        ("1-1-1", _candidate(ADD_ITEM), "body one", None),
        ("1-2", _candidate(TOTAL_PRICE), "body two", "snippet was paraphrased"),
    ])

    assert "PAIRS (2)" in prompt
    assert f"unit_id: {ADD_ITEM}" in prompt
    assert f"unit_id: {TOTAL_PRICE}" in prompt
    assert "body one" in prompt and "body two" in prompt
    assert prompt.count("A previous attempt at this claim was rejected") == 1
    assert "snippet was paraphrased" in prompt


def test_parse_batch_claims_keeps_the_good_and_drops_the_malformed():
    claims = parse_batch_claims({"claims": [
        {"requirement_code": "1-1", "unit_id": "a", "effect": "e",
         "evidence": "v"},
        {"requirement_code": "1-1", "unit_id": "b"},
        "not an object",
    ]})

    assert claims == [Claim("1-1", "a", "e", "v")]


def test_claude_backend_sends_one_batch_as_one_call():
    sent = []

    def runner(command):
        sent.append(command)
        return (
            '{"result": "{\\"claims\\": ['
            '{\\"requirement_code\\": \\"1-1\\", \\"unit_id\\": \\"a\\", '
            '\\"effect\\": \\"e\\", \\"evidence\\": \\"v\\"}]}"}'
        )

    llm = ClaudeCliLLM(runner=runner, body_reader=lambda fn: "body")
    model, _ = _mapped({}, mapped_ids=[ADD_ITEM, TOTAL_PRICE])
    functions = [model.functions[ADD_ITEM], model.functions[TOTAL_PRICE]]
    requests = [VerifyRequest("1-1", functions[0]), VerifyRequest("1-1", functions[1])]

    claims = llm._verify_claims(requests)

    assert len(sent) == 1
    assert "PAIRS (2)" in sent[0][2]
    assert claims == [Claim("1-1", "a", "e", "v")]


# --- --prompt-debug (D31) ---


def _frozen_log(tmp_path):
    moment = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    return PromptLog(tmp_path, clock=lambda: moment)


def test_prompt_debug_writes_a_log_with_headers(tmp_path):
    model, fake = _mapped(_all_good())
    fake.prompt_log = _frozen_log(tmp_path)

    run_verification(model, fake, CODEBASE, VerificationConfig(batch_size=3))

    logs = list(tmp_path.glob("prompts-mapper-*.log"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert text.count(HEADER_PREFIX) == 1
    assert "2026-08-23T12:00:00Z" in text
    assert "PAIRS (3)" in text


def test_prompt_debug_logs_mapping_prompts_too(tmp_path):
    model = load_ast_json(FIXTURES / "ast.json")
    load_into_model(model, FIXTURES / "requirements_wellformed.md")
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1-1-1": [ADD_ITEM]}))
    fake.prompt_log = _frozen_log(tmp_path)

    run_mapping(model, fake)

    text = list(tmp_path.glob("prompts-mapper-*.log"))[0].read_text(encoding="utf-8")
    assert "REQUIREMENT 1-1-1" in text
    assert text.count(HEADER_PREFIX) == len(fake.map_calls)


def test_no_log_is_written_when_prompt_debug_is_off(tmp_path):
    model, fake = _mapped(_all_good())

    run_verification(model, fake, CODEBASE, VerificationConfig(batch_size=3))

    assert list(tmp_path.iterdir()) == []
    assert fake.prompts == []


# --- the CLI wiring ---


def test_cli_rejects_a_batch_size_below_one(tmp_path, capsys):
    from meridian_mapper.cli import EXIT_CANNOT_RUN, main

    doc = tmp_path / "requirements.md"
    doc.write_text("1. Something\n", encoding="utf-8")

    code = main([str(FIXTURES / "ast.json"), str(doc), str(CODEBASE),
                 "--batch-size", "0"])

    assert code == EXIT_CANNOT_RUN
    assert "--batch-size must be at least 1" in capsys.readouterr().err


def test_cli_prompt_debug_writes_a_log_beside_the_artifacts(tmp_path):
    from meridian_mapper.cli import main

    fake = ScriptedFakeLLM(
        ScriptedScript(mappings={"1-1-1": [ADD_ITEM]},
                       claims={("1-1-1", ADD_ITEM): EVIDENCE[ADD_ITEM]})
    )
    argv = [str(FIXTURES / "ast.json"),
            str(FIXTURES / "requirements_wellformed.md"), str(CODEBASE),
            "--out", str(tmp_path / "mapping_ast.json"), "--batch-size", "2"]

    assert main(argv + ["--prompt-debug"], llm=fake) == 0

    logs = list(tmp_path.glob("prompts-mapper-*.log"))
    assert len(logs) == 1
    assert HEADER_PREFIX in logs[0].read_text(encoding="utf-8")


def test_cli_writes_no_log_without_prompt_debug(tmp_path):
    from meridian_mapper.cli import main

    fake = ScriptedFakeLLM(
        ScriptedScript(mappings={"1-1-1": [ADD_ITEM]},
                       claims={("1-1-1", ADD_ITEM): EVIDENCE[ADD_ITEM]})
    )
    argv = [str(FIXTURES / "ast.json"),
            str(FIXTURES / "requirements_wellformed.md"), str(CODEBASE),
            "--out", str(tmp_path / "mapping_ast.json")]

    assert main(argv, llm=fake) == 0

    assert list(tmp_path.glob("prompts-*.log")) == []
