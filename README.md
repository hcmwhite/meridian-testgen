# Meridian

Meridian is a grey-box, requirement-driven test-generation pipeline: it turns
a codebase plus a prose requirements document into a validated pytest suite,
using an LLM only where a deterministic tool can't do the job. It accompanies
the paper *Automated Quality Assurance for Vibe Coding* (PNSQC 2026), available
in the [PNSQC conference archives](https://www.pnsqc.org/archives/). <!-- TODO:
replace with the paper's direct archive URL once published -->

**The hypothesis under test:** does a structured, requirement-driven pipeline
produce a materially better (higher-coverage, more valid) test suite than
asking a frontier coding agent to "write tests for this app" with no
structure? The [`results/`](results/) directory is the evidence: every
Meridian-orchestrated run beat both un-orchestrated baselines on statement
coverage (86–94% vs. 55–62%), regardless of which backend model ran it.

## The pipeline

Three console tools (`pip install -e .` installs all three):

1. **`meridian-parser`** — deterministic, no LLM. Uses tree-sitter to extract
   the testable functions of a target codebase into structured JSON.
2. **`meridian-mapper`** — LLM. (a) Restructures a prose requirements doc
   into an enumerated hierarchy; (b) maps requirements onto the parsed
   functions, with a deterministic check that every mapped function actually
   exists (no hallucinated targets).
3. **`meridian-testgen`** — LLM. Generates pytest files per requirement,
   under a safety profile that forces fakes/mocks at hardware, network,
   subprocess, GUI, filesystem, and env-var boundaries. Generated tests are
   then executed and classified (see below), and wholly-invalid tests can be
   quarantined in place with `@pytest.mark.skip`.

The LLM backend is pluggable — `claude_cli` and `codex_cli` backends ship for
both the mapper and testgen stages. Design details: [`docs/SPEC.md`](docs/SPEC.md),
safety profiles: [`docs/CODEX_SAFETY_PROFILES.md`](docs/CODEX_SAFETY_PROFILES.md).

## Validity — how generated tests are judged

Each generated test file is executed in an isolated pytest subprocess and
every test case is classified:

- **passed** — ran, agreed with the code.
- **findings** — failed on `AssertionError`. Still a *valid* test: the
  disagreement is between the test's expectation and the code (or the
  requirement) — a candidate finding for human triage.
- **invalid** — died on any other exception (`KeyError`, `TypeError`, …):
  the test itself is defective in a way only execution reveals.

Valid = passed + findings. Invalid tests are excluded from all "how good is
this suite" analysis, including the corrected coverage numbers.

## The experiment

Target app: **rainbow_keys**, a small keyboard-synthesizer app (202 Python
statements), included here as [`rainbow_keys/`](rainbow_keys/). Six runs were
recorded — Meridian vs. a naive single-prompt baseline ("RAW"), across Claude
and Codex backends. Each run's full record (report, generated tests, prompt
logs) is under [`results/runs/`](results/runs/), and the summary tables the
paper's Figures 3 and 4 are built from are the CSVs in [`results/`](results/).

**Read [`results/README.md`](results/README.md) first** — it maps every CSV
row to its source run and its location in the paper, defines the column
semantics, and documents two measurement caveats.

To reproduce a row: `scripts/build_results_tables.py` re-executes a recorded
run's snapshotted tests against `rainbow_keys/` and recomputes its
classification and coverage numbers. Requirements: Python ≥ 3.10 with
`pytest`, `coverage`, and `numpy` (the audio device is faked by the tests —
no real audio hardware or `sounddevice` install needed; see
`rainbow_keys/python/requirements.txt`).

```sh
python -m venv .venv && .venv/bin/pip install -e ".[test]" coverage numpy
.venv/bin/python scripts/build_results_tables.py \
  --run-dir results/runs/20260825-051902Z_rainbow_keys_codex_cli \
  --mode Meridian --model "Codex 5.6-Terra" \
  --coverage-label meridian_codex_gpt-5.6-terra \
  --codebase rainbow_keys
```

## Reproducing the experiment

Running the full generation pipeline from scratch requires the `claude`
and/or `codex` CLI installed and authenticated (stages 2–3 make real LLM
calls; the recorded runs cost roughly $5 each). `<WORKDIR>` below stands for
any scratch directory of your choosing outside the repository.

```sh
# Stage 0 — setup, from a fresh clone
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"                       # meridian-parser / -mapper / -testgen
python3 -m venv rainbow_keys/.venv             # interpreter the generated tests run under
rainbow_keys/.venv/bin/pip install -r rainbow_keys/python/requirements.txt pytest coverage

# Stage 1 — deterministic parse (no LLM)
meridian-parser rainbow_keys --out <WORKDIR>/ast.json

# Stage 2 — requirement mapping (LLM)
meridian-mapper <WORKDIR>/ast.json rainbow_keys/SampleRequirements.md rainbow_keys \
  --out <WORKDIR>/mapping_ast.json             # writes mapping_requirements.json beside it

# Stage 3 — test generation (backend: claude_cli or codex_cli)
cp -R rainbow_keys <WORKDIR>/rainbow_keys_scratch   # scratch copy, as in the recorded runs
meridian-testgen <WORKDIR>/mapping_ast.json <WORKDIR>/mapping_requirements.json \
  <WORKDIR>/rainbow_keys_scratch \
  --python rainbow_keys/.venv/bin/python --out-dir <WORKDIR>/generated_tests \
  --backend claude_cli --llm-timeout 600

# Run the generated suite against rainbow_keys
rainbow_keys/.venv/bin/python -m pytest <WORKDIR>/generated_tests
```

To skip the LLM stages, start from the recorded artifacts instead:
[`results/inputs/`](results/inputs/) holds the exact `mapping_ast.json` and
`mapping_requirements.json` the runs consumed (feed them straight to
stage 3), and each run's generated suite is already snapshotted under
`results/runs/*/tests/`. To classify a run's tests the way the paper did,
use `scripts/record_run.py` and `scripts/build_results_tables.py` — see
[`results/README.md`](results/README.md).

## A note on provenance paths

In the run records under `results/runs/`, `<REPO_ROOT>` stands for the
checkout location of this repository. The records also reference scratch
workdirs under `/private/tmp/` and a
`results/rainbow_keys_snapshot_20260824_pre_safety/` directory that are
ephemeral and not part of this repository. The referenced inputs survive
here: the target app is
[`rainbow_keys/`](rainbow_keys/), and the mapper artifacts
(`mapping_ast.json`, `mapping_requirements.json`, `ast.json`,
`excluded.json`) are in [`results/inputs/`](results/inputs/).

## Repository layout

```
meridian_parser/    Stage 1 — tree-sitter extraction (no LLM)
meridian_mapper/    Stage 2 — requirements tree + mapping (LLM)
meridian_testgen/   Stage 3 — test generation, safety profiles, validation (LLM)
cli/                parse_ast.py — thin CLI entry
scripts/            record_run.py (run recorder/classifier), raw_baseline.py
                    (the RAW baseline), build_results_tables.py (results CSVs)
tests/              pytest suite for the three packages (399 tests)
docs/               design spec, safety profiles, backend notes
results/            recorded runs, summary and coverage tables — see its README
rainbow_keys/       the target app under test (Python core + Swift UI shell)
```

`rainbow_keys/` includes a Swift front end (`Package.swift`, `Sources/`)
because that's the real app; the experiment tests only its Python core
(`rainbow_keys/python/`, 202 statements).

## Development

```sh
pip install -e ".[test]"
pytest            # the repo's own suite (tests/), not the generated ones
```

`tests/fixtures/` contains `test_*.py` files that are parser *input*, not
part of the suite — pytest is configured to skip them (`norecursedirs`).

## License

MIT — see [LICENSE](LICENSE).
