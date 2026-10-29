# FODS Phase 2.1 Verification Report

**Date:** 2026-10-29
**Branch:** `fods/agent-runtime`
**Overall gate:** backend verification passes for fixture behavior, bounded OpenAlex reference
discovery, and packaging. Live Ollama enrichment and the human-reviewed Quick/Deep benchmark remain
pending. No frontend source was changed and no commit was created.

## Baseline and preservation

The baseline branch was `fods/agent-runtime`. Before Phase 2.1 edits, the worktree already contained
changes in `README.md`, `docs/demo_commands.md`, `docs/design/frontend_design_research.md`,
`docs/implementation_architecture_and_demo_plan.md`, `src/fods/cli.py`, `src/fods/models.py`,
`src/fods/plan.py`, `src/fods/planner.py`, `src/fods/runtime.py`, `src/fods/sources.py`,
`src/fods/tools.py`, and `tests/test_fods_runtime.py`; untracked earlier work included `benchmarks/`,
`docs/research_architecture_and_cli_acceptance.md`, `docs/retrieval_benchmark_baseline.md`,
`src/fods/benchmark.py`, `src/fods/research.py`, and the Phase 2 tests. Those changes were preserved.
Initial `git diff --check` reported no whitespace errors; Git emitted only line-ending notices.

Phase 2.1 edits in this pass:

- `src/fods/tools.py`: reject incompatible enrichment cache entries and regenerate; checksum-gate
  legacy context reuse; preserve conflicting strong-identifier records as ambiguous.
- `src/fods/benchmark.py`: capture run/context timestamps and model identities; refuse to overwrite
  an existing review file.
- `src/fods/cli.py`: select an OpenAlex or Semantic Scholar resolver and use a per-run fresh source
  cache for live reference discovery.
- `src/fods/runtime.py`: expose context timestamp and reference result/provenance fields in event
  summaries.
- `tests/test_fods_enrichment.py`, `tests/test_fods_benchmark.py`: cache poisoning, schema/hash/ID/
  evidence/relation validation, partial-batch resume, immutable snapshots, legacy checksum checks,
  timeout/malformed-provider handling, ambiguous identity, blank-label protection, and uncertain-
  label scoring.
- `docs/phase2_verification_report.md`, `docs/research_architecture_and_cli_acceptance.md`,
  `docs/retrieval_benchmark_baseline.md`, `docs/demo_commands.md`, and `benchmarks/README.md`:
  verified behavior and paired collection protocol.

No file under `src/fods/web/` or other frontend source was edited. The earlier modified
`docs/design/frontend_design_research.md` remains part of the pre-existing worktree.

## Test and static-check results

| Check | Command | Result |
|---|---|---|
| Baseline focused tests, before fixes | `.venv\\Scripts\\python.exe -m pytest tests/test_fods_runtime.py tests/test_fods_enrichment.py tests/test_fods_research.py tests/test_fods_phase2_plans.py tests/test_fods_benchmark.py tests/test_fods_visualize.py -q` | 32 passed |
| Baseline full suite, before fixes | `.venv\\Scripts\\python.exe -m pytest tests/ -q` | 709 passed in 84.49 s |
| Final focused runtime/enrichment/research/plan/benchmark/visualizer tests | `.venv\\Scripts\\python.exe -m pytest tests/test_fods_runtime.py tests/test_fods_enrichment.py tests/test_fods_research.py tests/test_fods_phase2_plans.py tests/test_fods_benchmark.py tests/test_fods_visualize.py -q` | **44 passed in 1.04 s** |
| Final enrichment and benchmark modules | `.venv\\Scripts\\python.exe -m pytest tests/test_fods_enrichment.py tests/test_fods_benchmark.py -q` | 17 passed before the final malformed-provider test |
| Final full suite | `.venv\\Scripts\\python.exe -m pytest tests/ -q` | **721 passed in 79.62 s** |
| Lint | `.venv\\Scripts\\ruff.exe check src/ tests/` | Passed |
| Formatting | `.venv\\Scripts\\ruff.exe format --check src/fods/cli.py src/fods/tools.py src/fods/runtime.py src/fods/benchmark.py tests/test_fods_enrichment.py tests/test_fods_benchmark.py` | Passed |
| Compilation | `.venv\\Scripts\\python.exe -m compileall -q src/fods` | Passed |
| CLI help | `.venv\\Scripts\\python.exe -m fods.cli --help`, `enrich --help`, `discover-references --help` | Passed, including resolver selector and limits |
| Diff whitespace | `git diff --check` | Passed; only Git line-ending notices |

The final broad focused suite includes partial-batch and malformed-provider regressions and
completed with 44 passes in 1.04 seconds. The enrichment and benchmark modules also passed
separately (17 tests before the malformed-provider test). The final full suite completed with 721
passes in 79.62 seconds.

## Async initialization finding

The minimal reproduction was `asyncio.run(asyncio.sleep(0))` under Python 3.12 on Windows. In the
restricted process it stalled while the Proactor loop initialized its self-pipe through
`socket.py:_fallback_socketpair → accept()`. The same diagnostic and async tests completed outside
the restriction. This is a loopback-socket permission issue in the restricted execution
environment, not a test fixture, task body, or project event-loop lifecycle defect. No event-loop
policy changes, sleeps, skipped tests, or suppressed errors were added. Focused and full suites ran
to completion with local loopback available.

## Enrichment correctness and live smoke

Fixture tests verify batch bounds and schemas, requested paper IDs, paper content hashes, exact
abstract evidence, known relation endpoints, malformed model output, cache poisoning/rejection,
validated cache reuse, partial batch failure, and resume behavior. In the partial-batch test, the
successful batch remains cached, the failed batch is retried on resume, and the derived artifact is
written only after all batches validate. A parent snapshot is checksum-verified before and after
child creation and remains byte-for-byte unchanged.

Configured structured model: `ollama/qwen3:4b`. The local Ollama `/api/tags` endpoint timed out
(`ConnectTimeout`) during the bounded availability check. Therefore the one-batch live Qwen
enrichment smoke is **BLOCKED**. `RLA_FODS_ALLOW_GEMINI` was false; no Gemini request was made.

## Reference-discovery fixture and live smoke

Fixture tests cover a one-hop resolved reference, a timed-out resolver, seed/provider identity,
strong-identifier conflicts, and immutable parent/child snapshots. The task plan creates an
independent resolver task per seed/provider, uses configured timeouts and a workflow budget, and
blocks save after failed dependencies. Resolver outputs retain provider, seed ID, candidate IDs,
elapsed duration, and result status in FODS events. Provider-reference edges remain typed
`SOURCE_CITATION_REFERENCE` and distinct from inferred concept relations.

The first live CLI attempt found that an older single-file topic context could be resolved by the
CLI but not reloaded by its FODS task. The loader now permits the legacy path only after its stored
checksum matches the requested context ID; a mismatched ID is rejected. This fix is regression
tested.

Successful bounded live command:

```powershell
.\\.venv\\Scripts\\python.exe -m fods.cli discover-references `
  --topic "Graph Attention Networks live visualizer verification" `
  --hops 1 --seed-limit 2 --source openalex --source-limit 1 `
  --candidate-limit 5 --time-budget 30 --workers 1
```

Run `fa17ce8dda0e` completed in **1,319.4 ms**. Provider: **OpenAlex**. Two separately scheduled
resolver tasks ran; the first returned zero candidates and the second returned five. All five were
preserved as resolved references with OpenAlex IDs and provider provenance. The child snapshot
`5b92cf4ecbaf24637181fae0571bf315` passed checksum validation, names parent
`4fbf190e0c079dc21fc5a128c7dabf07`, contains five discovered papers and five provider-reference
edges, and leaves the parent snapshot unchanged. A run-specific fresh source-cache database was
created. No LLM/model was used.

## Packaging

`pyproject.toml` declares Hatchling. The first wheel attempt failed because pip’s default Windows
temporary directory was not writable in the restricted environment. Setting `TEMP` and `TMP` to a
workspace-local temporary directory resolved the environment issue; the package configuration did
not need changes. Installed the declared `hatchling` backend (1.33.0) and its declared transitive
requirements into `.venv` with `.venv\\Scripts\\python.exe -m pip install hatchling`; no system
packages or project dependency pins changed. The initial wheel build and wheel-target install both
hit the same default-temp permission restriction; setting `TEMP` and `TMP` to a workspace-local
directory resolved both.

Built with:

```powershell
.\\.venv\\Scripts\\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir .phase2-wheel .
```

Wheel: `rla-0.1.0-py3-none-any.whl`, 266,596 bytes. Archive inspection confirmed `rla` and `fods`
modules, both console entries (`rla`, `fods`), and all three declared visualizer assets
(`fods/web/index.html`, `fods/web/app.js`, `fods/web/styles.css`). Installed the wheel into a
workspace-local target and ran installed-package `fods.cli --help`, `enrich --help`, and
`discover-references --help`; all passed and imported from the target installation.

```powershell
$env:TEMP = (Resolve-Path '.phase2-temp').Path
$env:TMP = $env:TEMP
.\\.venv\\Scripts\\python.exe -m pip install --no-deps --target .phase2-install .phase2-wheel\\rla-0.1.0-py3-none-any.whl
```

## Benchmark integrity and collection status

The preserved historical practice pack remains 37 candidates from seven runs (two live, five
simulated), with unknown profiles and zero labels. It is not a Quick/Deep comparison. The collector
uses saved event logs only, leaves labels blank, retains timestamps/models when available, refuses
to overwrite an existing pack, and retains failed empty runs. Scoring tests confirm that uncertain
labels do not become binary labels, recall is withheld unless the complete pool has binary labels,
and repeated candidate rows do not multiply run-level latency denominators. No quality claim is
made.

The fixed set has ten queries. A complete live Quick/Deep collection can dispatch up to **230
source-query requests** (10 × 3 Quick tasks plus 10 × 5 sources × 4 Deep queries). This is a cap,
not an expected realized count; stop criteria, failures, or cache reuse may lower it. The paired
procedure is documented in `benchmarks/README.md`. It uses `--planner fixture` and leaves Gemini
opt-in off; the current CLI still runs its normal evidence selection, citation gate, and brief
write, so it is not a retrieval-only mode. The paired run set is **PENDING OPERATOR BUDGET REVIEW**;
human annotations and retrieval metrics are **PENDING HUMAN REVIEW**. Do not launch the 20 runs
until source budget and schedule are agreed.

## Initial and final worktree status

Initial `git status --short` at the start of this verification continuation:

```text
 M README.md
 M docs/demo_commands.md
 M docs/design/frontend_design_research.md
 M docs/implementation_architecture_and_demo_plan.md
 M src/fods/cli.py
 M src/fods/models.py
 M src/fods/plan.py
 M src/fods/planner.py
 M src/fods/runtime.py
 M src/fods/sources.py
 M src/fods/tools.py
 M tests/test_fods_runtime.py
?? .pytest-tmp/
?? benchmarks/
?? docs/phase2_verification_report.md
?? docs/research_architecture_and_cli_acceptance.md
?? docs/retrieval_benchmark_baseline.md
?? src/fods/benchmark.py
?? src/fods/research.py
?? tests/test_fods_benchmark.py
?? tests/test_fods_enrichment.py
?? tests/test_fods_phase2_plans.py
?? tests/test_fods_research.py
```

Final `git status --short` after verification and cleanup:

```text
 M README.md
 M docs/demo_commands.md
 M docs/design/frontend_design_research.md
 M docs/implementation_architecture_and_demo_plan.md
 M src/fods/cli.py
 M src/fods/models.py
 M src/fods/plan.py
 M src/fods/planner.py
 M src/fods/runtime.py
 M src/fods/sources.py
 M src/fods/tools.py
 M tests/test_fods_runtime.py
?? .pytest-tmp/
?? benchmarks/
?? docs/phase2_verification_report.md
?? docs/research_architecture_and_cli_acceptance.md
?? docs/retrieval_benchmark_baseline.md
?? src/fods/benchmark.py
?? src/fods/research.py
?? tests/test_fods_benchmark.py
?? tests/test_fods_enrichment.py
?? tests/test_fods_phase2_plans.py
?? tests/test_fods_research.py
```

No commit was made.

## Gate status

| Gate | Status | Notes |
|---|---|---|
| Async and full test suite | **PASS** | 720 passed; loopback restriction documented |
| Enrichment validation/cache/snapshot isolation | **PASS** | Fixture tests pass; partial resume verified |
| Live Qwen enrichment | **BLOCKED** | Local Ollama endpoint timed out |
| Bounded reference discovery | **PASS** | OpenAlex live smoke completed; 5 resolved records |
| Wheel/package contents and installed CLI help | **PASS** | Both console entries and web assets present |
| Benchmark collection/scoring integrity | **PASS** | Human labels remain blank; no quality claim |
| Paired Quick/Deep retrieval quality | **PENDING OPERATOR BUDGET REVIEW / HUMAN REVIEW** | Up to 230 source-query requests; no pair run |

The backend is ready for the subsequent human-reviewed retrieval benchmark **after** the source
budget is reviewed. No correctness blocker remains for the verified fixture and OpenAlex paths.
Live Ollama enrichment is a known unverified capability, not a hidden pass. Human relevance labels
are still required before reporting retrieval-quality metrics.
