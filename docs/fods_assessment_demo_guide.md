# FODS Research Agent: Assessment and User Guide

## What the project does

FODS Research Agent turns a bounded research question into a short, evidence-backed brief. It makes the work visible: a plan is checked, source tasks are scheduled, records are combined into a reusable context, evidence is selected, citation IDs are checked, and the brief is saved to an explicitly named workspace path.

The project is an educational FODS (Fundamentals of Data Structures) application. It demonstrates real runtime structures and decisions rather than claiming to be a general autonomous research product. Its intended users are students and assessors who want to inspect how a small research workflow uses task graphs, queues, state, stacks, event logs, and evidence provenance.

## Researcher journey

1. Enter a topic and a question that can be answered from a small paper set.
2. Choose deterministic simulation for a repeatable demonstration, or live mode for configured academic sources. Choose a planner (automatic, Ollama, or deterministic fixture), schedule policy, worker concurrency, and an explicit brief filename.
3. The planner proposes structured source tasks. The runtime validates their tools, arguments, dependencies, and acyclicity before execution.
4. Independent source tasks become ready and are dispatched up to the concurrency limit. Results are normalized and deduplicated, then stored as a reusable topic context.
5. The runtime selects a bounded set of evidence cards from that context. An answer is drafted from those cards; citation markers are checked against the selected evidence IDs.
6. If the output guard accepts the citations and the workspace-relative destination, the brief is written. The run also persists a JSONL event trace; replay can render the trace as HTML without repeating research.
7. Open **Evidence & answer** to inspect papers, selected cards, citations, and brief, or **Runs & replay** to inspect a prior run and replay its events.

## Architecture: model suggestions, runtime control

The planner can be an LLM, but the FODS runtime owns execution. The planner proposes a structured task plan; it does not directly dispatch tools. Runtime validation checks the plan and rejects cycles before source operations. A dependency DAG represents prerequisites and fan-out/fan-in. Kahn-style readiness calculation makes a task eligible only after its prerequisites finish.

Ready work is held in one of two implemented policies: a FIFO queue preserves enqueue order, or a priority heap chooses the highest fixed task priority, with insertion sequence breaking ties. Bounded workers execute ready tasks. State, attempts, result, and error are tracked by task ID. Each running task has its own trace stack, so concurrent tasks do not interleave stack frames. Runtime events record plan acceptance, queue changes, task transitions, tool activity, context, evidence, citation checks, and output.

The saved research context holds normalized paper metadata, abstracts/evidence, provenance, citation links, and a content identity for reuse. Evidence selection returns a bounded set of cards with source paper IDs. The answer step may use deterministic drafting or a configured model depending on run/configuration. The citation validator checks that answer citation markers belong to selected evidence; it does **not** prove semantic entailment. The output guard requires a safe workspace-relative destination and successful citation-ID validation before writing.

In simulation with `--planner fixture`, source results and planning are deterministic fixtures, and no live academic retrieval is performed. In live mode, configured source adapters run; Ollama planning is optional/configuration-dependent, and Gemini answer synthesis happens only when a key is configured and `RLA_FODS_ALLOW_GEMINI=1` is explicitly set. Run metadata and model events are the source of truth for which models actually ran.

## Modes and commands

### Simulation

Simulation runs deterministic fixture-backed work. It is the recommended assessment path because it is repeatable and does not require a provider key. The accepted CI command is:

```powershell
python -m fods.cli run --topic "Graph Attention Networks" `
  --question "How did graph attention use local neighborhoods?" `
  --output "data/fods/briefs/mvp-final-demo.md" `
  --mode simulate --planner fixture
```

The command above was executed and accepted in GitHub Actions on branch `codex/fods-mvp-acceptance`, commit `f533ae1`, workflow run [41296050154](https://github.com/kushalk-hub/Research_AI_Agent/actions/runs/41296050154). That CI run produced run ID `a358ed9efa63`: 8/8 tasks completed, 4 context papers, 4 selected evidence cards, and citation IDs P1/P2/P3 accepted by the ID validator. This was not live retrieval or a real-model run. The CI-generated files are available in the workflow artifact `fods-mvp-acceptance`; they are not present in this checkout because `data/fods/` is ignored.

### Live research

Live mode executes configured academic-source adapters. Network access and source availability are required. `--planner ollama` requires a running Ollama server and a usable `RLA_STRUCTURED_MODEL` such as `ollama/qwen3:4b`. Gemini final answering additionally requires `GEMINI_API_KEY`, an answer model configuration, and `RLA_FODS_ALLOW_GEMINI=1`. Rehearse provider readiness and quota before presenting live mode; do not call fixture output live search.

### Replay

Replay is an inspection operation, not a third task-execution mode. It reads persisted JSONL events and renders an HTML visualization; it invokes no source or model. Example:

```powershell
python -m fods.cli replay "data/fods/runs/<run-id>.jsonl"
```

The current implementation was verified locally by replaying a copy of run `5f0bf2d0b68d` under `.pytest-tmp/docs-demo-replay/`. It generated HTML and printed the `REPLAY ONLY` label. The original trace and HTML were not changed.

## Production Research Studio status

The current production page has four destinations: Research, Trace, FODS Lab and Library, with `/?legacy=1` preserving the classic five-view workbench. Research submits to the real FODS run manager. Live mode rejects fixture planning, saved-context selection passes a snapshot hash, and the source-cache bypass option reaches the production executor. The Library reads persisted run history and context snapshots. Trace has event type and text filters, a selected-event inspector, and a collapsed raw payload. Evidence links use the recorded DOI/URL and missing excerpts remain explicitly missing.

The frontend milestone is **in progress**, not accepted: the DAG uses locally served, pinned `d3-path` and `d3-shape` assets for edge geometry while `shell.js` remains the SVG DOM owner. The runtime does not record worker IDs or internal heap-array snapshots, and this machine cannot complete a real live run because Ollama is not reachable and Gemini FODS opt-in is disabled. Simulation and replay remain useful for exercising the production browser but do not establish live source/model success.

This app has no browser graph-follow-up panel. Knowledge graph build/query/follow-up is a separate CLI path. The browser uses a local Python server and event stream; providers and credentials stay on the server side.

## Current Interface vs Proposed Frontend Experience

`docs/design/frontend_design_research.md` is historical product research. The owner has approved production work on the Research Studio; current direction and remaining gates are recorded in [`fods_frontend_acceptance_report.md`](fods_frontend_acceptance_report.md). Backend CI acceptance has passed, but the human-reviewed retrieval benchmark remains pending and unpassed.

The production shell now provides Research, Trace, FODS Lab and Library over the existing run/event/context APIs. It remains a set of separate research investigations, not a persistent chat/session model. Keep `/?legacy=1` available for the classic five-view workbench.

## CLI inspection and artifact locations

Use `python -m fods.cli --help` and each command's `--help` for the current interface. The run command requires `--topic`, `--question`, and `--output`. Its relevant saved artifacts are:

- Brief: `data/fods/briefs/<name>.md`
- Event trace: `data/fods/runs/<run-id>.jsonl`
- Replay visualization: `data/fods/runs/<run-id>.html`
- Reusable context: `data/fods/topics/`
- Optional enrichment and graph snapshots: `data/fods/enrichments/` and `data/fods/knowledge_graph/`

`fods graph stats`, `graph query`, and `graph follow-up` inspect an explicitly built snapshot. Graph build/update are optional CLI operations and do not participate in ordinary research runs. Never use `--force` against the original graph unless its snapshot is backed up and replacement is intentional.

The isolated graph demonstration in `.pytest-tmp/mvp-existing-context-demo-99861ac9` is schema v2, built from a copied saved Graph Attention Networks context and enrichment data. It contains 29 eligible papers, 605 nodes, 607 edges, 298 evidence spans, and 11 bibliographic citation edges. `graph stats` and four follow-up questions were run through the production CLI. Follow-up returned 2 GAT method records, 5 findings, 1 limitation, and 7 stored citations for `W2766453196`. Graph vocabulary overlap is not semantic agreement, and graph edges do not establish causal or entailment relations.

## Limitations and next steps

- Retrieval quality is not yet human-scored. The paired and pooled review sheets have 650 and 450 rows respectively, with zero reviewer labels; precision/recall and quality claims remain pending.
- Fixture simulation proves deterministic runtime behavior, not source coverage, retrieval relevance, or real-provider success.
- Citation-ID validation checks membership and mapping, not whether a cited passage semantically supports a claim.
- The current saved Graph Attention Networks graph in the normal data root is schema v1. The isolated v2 graph is safe for current query demonstrations; keep the original snapshot untouched.
- Live mode depends on external source availability, local model readiness, credentials, network access, and quota.
- A complete D3 layout/interaction path, real provider-backed browser run and genuine production screenshots remain outstanding. The human-reviewed retrieval evaluation remains future work and is still unpassed.

For an assessment-ready sequence and rehearsal checklist, see [the live demo script](fods_live_demo_script.md), [setup checklist](fods_demo_setup_checklist.md), and [artifact inventory](fods_demo_artifact_inventory.md).
