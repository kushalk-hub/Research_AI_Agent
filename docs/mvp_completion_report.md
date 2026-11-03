# FODS Research Agent MVP Completion Report

**Backend acceptance: PASSED in CI** (2026-11-01). **Human-reviewed retrieval quality: PENDING.**

This report originally recorded a local Windows run blocker. That historical observation remains
accurate for the local environment at that time, but it has been superseded for backend acceptance
by the successful GitHub Actions run documented in the [CI acceptance closeout](#ci-acceptance-closeout).
The project-level retrieval-quality gate remains separate and incomplete until the benchmark rows
receive independent human labels.

The faculty-facing walkthrough package is in the [assessment guide](fods_assessment_demo_guide.md),
[live demo script](fods_live_demo_script.md), [setup checklist](fods_demo_setup_checklist.md), and
[artifact inventory](fods_demo_artifact_inventory.md).

FODS is the primary research-to-brief application in this repository. Its main workflow and the
optional graph follow-up path are implemented. The graph path was exercised against an isolated
copy of the saved Graph Attention Networks context and enrichment artifacts. In the original
local Windows verification pass, loopback restrictions prevented an end-to-end run; the later CI
acceptance closeout below ran and validated the deterministic fixture workflow successfully.

## Application relationship and architecture

`pyproject.toml` names the Python distribution `rla` and registers two separate console entry
points:

| Command | Role |
|---|---|
| `fods` / `python -m fods.cli` | **Primary application.** Research-to-brief workflow and deterministic FODS task runtime; optional enrichment, reference discovery, graph, replay, and browser visualizer commands. |
| `rla` | Companion research-literature CLI with its own pipeline, graph traversal, TUI, reports, and evaluation commands. It is not an alias for FODS and does not call the FODS task scheduler. |

FODS reuses selected `rla` components: `Paper` and content hashes, configuration, source metadata
normalization and deduplication, model/client interfaces, request caching, and rate-limit controls.
FODS execution is controlled in `fods.runtime.run_plan`; `fods.cli._execute` constructs and
validates a task plan, supplies the tool registry, and awaits the deterministic scheduler. The
runtime controls readiness, dependencies, bounded dispatch, task state, events, and completion.
Research and graph operations remain separate: graph build/update are explicit commands and are
not required for the initial brief.

## Main research workflow

The FODS run command connects request planning, source-task execution, paper normalization and
deduplication, deterministic relevance ranking, context persistence, evidence selection, answer
drafting, citation-ID validation, and the brief write. In `simulate` mode it uses bundled fixture
papers with a deterministic planner; it does not contact academic sources or call a model. Live
mode retrieves from configured academic sources and requires reachable providers. `--planner
ollama` requires a usable Ollama model. A Gemini final-answer call additionally requires a
configured key and `RLA_FODS_ALLOW_GEMINI=1`.

Enrichment is a separate optional operation, not a prerequisite for producing a brief. The local
Ollama `fods enrich` command writes validated derived artifacts for the saved context. Explicit
graph build then indexes only eligible enrichments. Citation-ID validation confirms cited IDs map
to selected evidence; it does not establish semantic entailment of every sentence.

### Primary deterministic demonstration

The acceptance command uses a new output path:

```powershell
python -m fods.cli run --topic "Graph Attention Networks" `
  --question "How did graph attention use local neighborhoods?" `
  --output "data/fods/briefs/mvp-final-demo.md" `
  --mode simulate --planner fixture
```

At the time of this original local verification note, this command was **not executed** in the
restricted Windows environment because asyncio loopback initialization failed before `run_plan`
started. The later CI execution and its actual run ID/artifacts are recorded below. The command
above is the acceptance command for an
unrestricted environment.

When it succeeds, the explicit brief path is under `data/fods/briefs/`; context snapshots are
under `data/fods/topics/`; JSONL run traces and their HTML visualizations are under
`data/fods/runs/`. The CLI prints the run ID and task events. Inspect/replay a trace with:

```powershell
python -m fods.cli replay "data/fods/runs/<run-id>.jsonl"
```

Replay reads events and creates an HTML visualization; it does not rerun the research tasks.

## Optional graph follow-up demonstration

The existing saved Graph Attention Networks snapshot is schema v1. The current `graph stats`
command can inspect it, but the v2 query implementation rejects it. The original context,
enrichment records, and published snapshot were left unchanged.

For a current-schema demonstration using the existing research artifacts, this pass copied the
saved context `6027ff84b166b45f6ac9955ba3f58b83` and its 15 matching enrichment files to an
isolated directory under `.pytest-tmp/`. The actual production Typer CLI then ran `graph build`,
`graph stats`, and `graph follow-up` against that copied data. The generated v2 snapshot is:

`.pytest-tmp/mvp-existing-context-demo-99861ac9/data/fods/knowledge_graph/887437c0b2403e8b/graph.json`

The isolated build selected **29 eligible papers** and produced **605 nodes / 607 edges** (298
evidence spans and 11 bibliographic citation edges); build time reported by that CLI run was
77.2 ms. The eligibility filter excluded ineligible/ambiguous records instead of rewriting them.

The production CLI follow-up results included:

- `Which papers use GAT?` — 2 exact method records. `W3171970564` links GAT to segment `S001`;
  `doi:10.3390/electronics13214208` links GAT to segment `S004`.
- `Which papers discuss graph attention networks?` — 6 exact concept records with source excerpts.
- `What findings are reported for graph attention networks?` — 5 evidence-backed finding records.
  For example, `W3146788459` reports “47% relative improvement” with segment `S009`; the excerpt
  is the source sentence about a 47% relative performance improvement.
- `What limitations are mentioned for graph attention networks?` — 1 evidence-backed limitation:
  `W3171970564`, “static attention hinders GAT from even fitting the training data,” segment
  `S005`.
- `Which papers cite W2766453196?` — 7 stored bibliographic citations, including
  `W2906413107` (Relational Graph Attention Networks).
- `Does GAT improve accuracy?` — clear unsupported-query guidance, with a structured-query
  fallback.
- A supported question with an empty graph — clear missing-snapshot guidance; no graph was built.

The retained snapshot and build report are isolated under the `.pytest-tmp` path above. These graph
results are from the saved real context and enrichment artifacts copied into a temporary data
root; they are not results from the unexecuted fixture brief run. To replace the original v1 graph
in a normal workspace requires the explicit `--force` option. Back up the old snapshot before
doing that. Follow-up queries never rebuild automatically.

## Historical local verification (before CI acceptance)

Checks executed in this pass:

| Command / check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests/test_fods_graph_followup.py tests/test_fods_graph_cli.py tests/test_fods_knowledge_graph.py -q --basetemp=.pytest-tmp/mvp-last-final` | **40 passed in 5.21 s**, exit code 0 |
| `.venv\Scripts\ruff.exe check src/ tests/` | **Passed**, exit code 0 |
| `.venv\Scripts\python.exe -m compileall src/fods` | **Passed**, exit code 0 |
| `python -m fods.cli run --help` | **Passed**, exit code 0; required arguments and modes match the documented acceptance command |
| Persisted artifact graph CLI demonstration (copied context/enrichments under `.pytest-tmp`) | Build, stats, method, concept, finding, limitation, citation, unsupported, and missing-snapshot commands returned exit code 0; evidence and citations inspected |

Prior selected synchronous checks recorded in the preceding completion pass were **11 passed,
50 deselected** for runtime-plan and retrieval-normalization cases. They do not constitute an
end-to-end run. The async runtime tests, P4 graph-stage suite, and full suite are not claimed as
passing.

## Historical local execution environment check

The following describes the environment during the original local verification pass; the later
CI result below supersedes its statement that the fixture gate remained unrun.

- At the start of the acceptance preparation there was no `.github/workflows` CI workflow. The
  acceptance workflow has since been added, but the installed GitHub CLI reports its configured
  account token is invalid, so no remote runner could be inspected or dispatched.
- WSL is present as a Windows command but `wsl --list --quiet` returns `Wsl/E_ACCESSDENIED`.
- The prior diagnostics reproduced loopback TCP connection denial (`WSAEACCES` / WinError 10013)
  across supported Python versions; asyncio stalls while initializing its self-pipe. No security
  settings were changed, and the fixture command was not repeatedly retried.
- The saved v1 graph is inspectable but not queryable by current v2 follow-up commands until it is
  explicitly rebuilt. The isolated v2 demonstration avoided replacing it.
- At that time, the exact fixture run still needed execution in an unrestricted Windows or CI
  environment. This was subsequently completed in CI as recorded below.
- Live-source retrieval and current Ollama/Gemini execution remain provider-dependent. Retrieval
  relevance still needs human labels, and citation validity is not a semantic-support evaluation.

No provider calls or edits to the original context, enrichment corpus, or published graph snapshot
were made. Graph demo files and measurements were written only under `.pytest-tmp/`.

## Historical CI acceptance workflow preparation (2026-11-01)

This section records the state before the workflow was dispatched. Its final “not run” statement
was accurate at that point only and is superseded by the following closeout.

The deterministic acceptance gate is now prepared in
`.github/workflows/fods-mvp-acceptance.yml`. It runs on manual dispatch, pull requests targeting
`main`, and pushes to `main` or `codex/fods-mvp-acceptance`, using an Ubuntu GitHub-hosted runner
and Python 3.12. The job installs
the existing `.[dev,tui]` extras, runs the fixture command below, validates its actual brief and
trace, then runs the P4 graph tests, full test suite, Ruff, and FODS compilation. The artifact step
runs even after earlier job failures and uploads the requested brief plus JSONL and HTML traces
created in that clean CI workspace. The workflow references no repository secrets and supplies no
provider credentials.

```bash
python -m fods.cli run \
  --topic "Graph Attention Networks" \
  --question "How did graph attention use local neighborhoods?" \
  --output "data/fods/briefs/mvp-final-demo.md" \
  --mode simulate \
  --planner fixture
```

The validation helper is `tools/validate_fods_mvp_artifacts.py`. Its smoke check against the
existing successful historical fixture artifacts passed: run `5f0bf2d0b68d`, 8 of 8 tasks, 4
context papers, 4 selected evidence cards, citations `P2`, `P3`, and `P4` validated, and the brief,
JSONL trace, and HTML visualization were present. This verifies the validator against the stored
event format only; that historical run has a different topic and output path and is **not** the
requested 2026-11-01 acceptance execution. Its old artifacts were not altered.

Supporting local checks for this preparation passed:

- `.venv\Scripts\ruff.exe check src/ tests/ tools/validate_fods_mvp_artifacts.py` — exit 0.
- `.venv\Scripts\python.exe -m compileall src/fods` — exit 0.
- `git diff --check` — exit 0; Git emitted only Windows line-ending normalization notices.

P4 and the full test suite were not rerun in this preparation pass.

At the time of writing this preparation snapshot, the workflow had not run and the local CLI token
was invalid. The later successful run is recorded below.

Pushing this workflow on the `codex/fods-mvp-acceptance` branch triggers the acceptance job there.
The repository owner could also open GitHub **Actions → FODS MVP acceptance → Run workflow** and
select that branch, or open a pull request targeting `main`. The uploaded artifact is named
`fods-mvp-acceptance`.

## CI acceptance closeout (2026-11-01)

The backend acceptance workflow passed on branch `codex/fods-mvp-acceptance`, commit `f533ae1`,
in [GitHub Actions run 41296050154](https://github.com/kushalk-hub/Research_AI_Agent/actions/runs/41296050154).
The accepted deterministic fixture run was `a358ed9efa63`: 8/8 tasks completed with zero failed
task attempts, 4 context papers and 4 selected evidence cards; citation IDs P1, P2, and P3 mapped
to selected evidence and passed the validator. The brief, JSONL trace, and HTML visualization
were uploaded as the `fods-mvp-acceptance` artifact. These are CI-generated files and are not in
the local checkout because `data/fods/` is ignored.

CI results: **797 full-suite tests passed**, **28 P4 graph-stage tests passed**, Ruff passed,
`compileall` passed, and artifact validation succeeded. This closes the backend acceptance gate.
It does not close retrieval-quality evaluation: the paired review file has 650 observations and
zero reviewer labels; the pooled review file has 450 observations and zero reviewer labels.
Human-reviewed relevance metrics remain **PENDING**. Citation-ID validation is not semantic
entailment evaluation. The proposed Chat/Trace/FODS Visualizer redesign remains deferred pending
the human-reviewed benchmark gate.

The currently implemented browser workbench still requires a reachable local loopback server.
In this Windows environment the server startup command succeeded, but browser access at
`127.0.0.1:18765` timed out and a PowerShell request received `WSAEACCES`; therefore local browser
rehearsal has not been verified here. The deterministic CI artifacts and the separate local
fixture replay remain safe presentation fallbacks.
