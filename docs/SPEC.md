# Meridian — Production Spec (supplement to the design handoff)

This document records the design-author's answers to the implementer's questions.
It supplements `design_handoff_meridian/README.md`, which remains the authority on
UI layout, visual tokens, interaction states, and the stub algorithms.

## Platform & stack

Local web app + local service, same shape as the prototype — no desktop wrapper.
Greenfield: no existing codebase or design system to fit into. Frontend is a
standard web stack; backend is a local service process the frontend talks to
over HTTP on localhost.

## Pipeline

### Derive AST — deterministic, no LLM

- Off-the-shelf parser; **tree-sitter** is the default choice (one consistent
  API across languages, which matters for the multi-language requirement below).
- The AST is the parser's native tree, decomposed to JSON with at minimum:
  node type, name (function/method/class identifiers), source location
  (file, line range), and parent-child structure down to method-level
  granularity.
- Persisted as JSON; read back into memory for later steps.

### Map AST — LLM, two neural sub-steps

Model-agnostic and configurable: the model/provider is a config value behind an
interface, never hardcoded. Do not bake in assumptions about a specific
provider's context window or tool-calling format — models will be swapped for
experimentation.

1. **Requirements extraction** — input: raw requirements document text.
   Output: a hierarchical requirements tree (JSON) preserving parent-child
   relationships as written. Not independent-sentence slicing; dependent /
   related requirements must stay linked.
2. **Mapping** — input: the requirements tree plus the AST. Output: a
   bipartite edge list; each edge is a (requirement node ID, code region
   reference) pair, where a code region reference is file + line range or an
   AST node ID — never full file contents.

### Test generation — real, in-scope, later phase

Downstream of mapping; not built now, but the extension point must be clean.
It will consume: one requirement, its mapped code region, and a propagated
structural-obligation checklist (test every method, handle null, handle
boundaries) for that region. It will eventually need its own UI surface
(likely a third stage after mapping — select a requirement, see its generated
tests), but that surface is not designed yet.

## Language scope

Not Python-only. The AST layer needs a parser abstraction from the start —
forced by the first real test case (**Rainbow Keys**: SwiftUI + Python logic in
one codebase). Concrete targets: **Python and Swift** first.

## Limits & scale

The prototype's 12-file / depth-6 caps are placeholders — keep them as
configurable soft limits, easy to raise. Do not invest in scale engineering;
this is a research prototype and realistic production scale is undetermined.

## Persistence

Local files; no database required. Persist per-project, keyed by project
folder path:

- derived AST (JSON)
- uploaded requirements (original + extracted tree)
- computed mapping (edge list)

SQLite is acceptable if it meaningfully simplifies things, but this is a
placeholder decision, not locked in.

## Requirements document formats

Current scope only (markdown, numbered clauses, bullets, JSON). No Word / PDF /
DOORS ingestion now. Structure the parser so a new format is an additive
adapter, not a rework.

## Non-goals, constraints, success criteria

- **Non-goal**: not a general-purpose IDE plugin or CI tool — it is a research
  instrument for studying requirement-to-code mapping accuracy.
- **Primary success criterion**: correctness and *inspectability* of the
  mapping step, over speed or polish. When a design choice trades
  mapping-error visibility for performance or slicker UX, prefer visibility.
- **Load-bearing boundary**: AST derivation (deterministic) and
  requirement-to-region mapping (neural) must remain cleanly separable in the
  code — never merged for convenience.
- **Deployment**: local use only; not building for distribution.
