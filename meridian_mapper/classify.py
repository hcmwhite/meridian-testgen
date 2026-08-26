"""The structural-test-only cleanup pass (D19, chunk 5).

After every requirement has been mapped and verified — and after verification
exhaustion has removed whatever it removed — any ast function left with no
requirement assignments is tagged ``structural_test_only``. Such a function
satisfies no stated requirement, so stage 3 owes it only the structural
obligations (it imports, it is callable, its signature holds), not a
behavioural test.

This is a pure pass over the model, run once, at the end. It is deliberately
*not* an inline decision inside the mapping or verification loops: a function
can pick up its only assignment from the last requirement in the document, and
can equally lose its only assignment to the last retry of the last pair. Only
after both loops have finished is "no remaining assignments" a true statement.

A function whose only mapping was removed by exhaustion therefore ends up
carrying both the tag and its error note (D18, D20) — the tag says stage 3 has
no requirement to test it against, the error note says why.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassifySummary:
    """What the pass did, for the CLI's run summary (chunk 6)."""

    total: int = 0
    structural_test_only: int = 0
    mapped: int = 0


def classify(model) -> ClassifySummary:
    """Tag every unmapped ast function ``structural_test_only``.

    Idempotent: the tag is recomputed from the current assignments each time,
    so running the pass twice — or running it after a later change to the
    model — never leaves a stale tag behind.
    """
    summary = ClassifySummary()
    for function in model.ordered_functions():
        summary.total += 1
        annotation = function.annotation
        unmapped = not annotation.requirement_codes
        annotation.structural_test_only = unmapped
        if unmapped:
            summary.structural_test_only += 1
        else:
            summary.mapped += 1
    return summary
