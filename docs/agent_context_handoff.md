# FODS Research Agent — Project Context Handoff

**Audience:** the coordinating/master agent that guides the implementation agent.
**Purpose:** orient the master agent quickly to the project goal, current architecture, code map,
verified implementation, and open gates. This is a navigation and status brief; the linked project
documents remain authoritative for their own subjects.

## How to use this handoff

Read this file first, then use the linked source-of-truth documents for decisions:

1. [`master.md`](master.md) defines project scope and the educational FODS purpose.
2. [`implementation_architecture_and_demo_plan.md`](implementation_architecture_and_demo_plan.md)
   defines the architecture and demo story.
3. [`research_architecture_and_cli_acceptance.md`](research_architecture_and_cli_acceptance.md)
   defines the active backend/CLI behavior and acceptance gates.
4. [`phase2_verification_report.md`](phase2_verification_report.md) records what was actually
   verified in the latest Phase 2.1 pass.
5. [`retrieval_benchmark_baseline.md`](retrieval_benchmark_baseline.md) and
   [`../benchmarks/README.md`](../benchmarks/README.md) govern benchmark claims and collection.
6. [`../AGENTS.md`](../AGENTS.md) governs repository commands, environment setup, and coding
   invariants. `PLAN.md` is the RLA milestone/status document; it does not replace the FODS master
   scope.

Treat code, tests, CLI help, and current configuration as behavior evidence. Treat older docs and
historical run artifacts as claims to verify when they disagree with current behavior.

## Project goal

Build an educational research-paper agent that turns a question into a reusable, evidence-backed
brief while making FODS data structures visible as real runtime machinery. The project demonstrates
that the runtime—not the LLM—owns plan validation, DAG readiness, task scheduling, task state,
bounded retries, trace events, citation checks, and safe output writes.

The key design principle is: **the model proposes meaning; FODS controls execution.** Keep the
first useful context fast: acquire paper metadata and abstracts, persist a reusable snapshot, then
answer from a small selected evidence slice. Concept enrichment is optional and resumable; it must
not block the first answer.

## Current architecture

```text
Question + topic
  → deterministic or optional Ollama intent/query planning
  → proposed research task plan
  → schema/tool/dependency validation and cycle rejection
  → FODS DAG readiness + FIFO or priority ready queue + bounded workers
  → one source/query request per task
  → normalize, conservatively deduplicate, rank, and persist an immutable context snapshot
  → retrieve a bounded evidence slice for the follow-up question
  → draft a cited answer
  → validate citation IDs against selected evidence
  → write only to the explicitly named path inside the approved workspace
  → retain events for CLI output, browser visualization, and replay
```

Optional later work runs after the answerable context exists:

- **Enrichment:** Ollama extracts abstract-grounded concepts, methods, findings, limitations, and
  relations in bounded batches. Validated outputs live in separate derived artifacts; content-hash
  cache keys support resume. Enrichment does not mutate the parent context.
- **Reference discovery:** one-hop lookups run as one FODS task per seed/provider. Provider
  citation edges remain distinct from inferred concept relations; a successful run writes a child
  snapshot that points to its parent.

The same canonical event stream feeds command output and the visualizer. The browser displays
runtime events; it does not schedule work or call models/sources. Distinguish **live** execution,
**simulation** through the actual scheduler with fixtures, and **replay** of recorded events. Replay
proves reproducibility, not live concurrency.

## FODS concepts and their implementation

| Concept | Main code | Observable proof |
|---|---|---|
| DAG and cycle detection | `src/fods/plan.py` | Invalid dependency cycles are rejected before tools run |
| Topological readiness and scheduling | `src/fods/runtime.py` | Ready, enqueue, dequeue, dependency, and task-state events |
| FIFO and priority queues | `src/fods/runtime.py` | Same ready set can be compared under two policies |
| Bounded concurrency and recovery | `src/fods/runtime.py` | Per-task start/end, retries, cancellations, blocked descendants, stop reason |
| State/result maps | `src/fods/runtime.py` | Task IDs resolve to task records, states, attempts, and outputs |
| Stack trace | `src/fods/tracing.py`, `src/fods/runtime.py` | Nested run/task/tool/model push/pop events |
| Event log and visualization | `src/fods/events.py`, `src/fods/visualize.py`, `src/fods/webapp.py` | JSONL, standalone HTML, local web UI, and replay share run events |
| Provenance/evidence gate | `src/fods/tools.py` | Selected evidence and citation IDs are checked before output write |

## Code map

### Research knowledge layer: `src/rla/`

The established RLA package owns reusable research-domain pieces: provider-neutral paper models,
academic source adapters, model/configuration support, SQLite caching, and the older research
pipeline for acquisition, extraction, resolution, graph building, traversal, answers, and evaluation.
FODS reuses these interfaces where appropriate. Do not broadly rewrite RLA or duplicate its source
and model infrastructure without evidence that a narrow adapter is insufficient.

### FODS runtime layer: `src/fods/`

| File | Responsibility |
|---|---|
| `cli.py` | `fods run`, `enrich`, `discover-references`, `replay`, and `serve`; builds plans and configuration |
| `models.py` | Task, plan, task-state, and run-result contracts |
| `plan.py` | Plan schema, tool argument checks, workflow-shape rules, DAG cycle/readiness validation |
| `planner.py` | Deterministic task planning and validated LLM-proposed task plans |
| `runtime.py` | Ready queues, bounded worker dispatch, state transitions, retries, dependencies, cancellation, and events |
| `tools.py` | Source search, context save/load, evidence retrieval, cited answer, citation validation, safe write, enrichment, and reference discovery |
| `sources.py` | RLA source adapter bridge and bounded live provider pool |
| `research.py` | Quick/Deep policies, query intent, query planning, deduplication, ranking, and context metadata |
| `events.py` | Canonical event schema, JSONL logging, reading, and event emission |
| `tracing.py` | Model-call instrumentation and nested activity tracing |
| `visualize.py` | Standalone HTML view rendered from recorded events |
| `webapp.py` | Local Python API and event stream for the interactive browser UI |
| `benchmark.py` | Offline review-pack collection and human-label-only scoring |
| `fixtures.py` | Deterministic paper/source data for keyless demos and tests |
| `safety.py` | Workspace/path safety helpers |
| `web/` | Packaged visualizer assets: `index.html`, `app.js`, `styles.css` |

### Tests and configuration

- `tests/test_fods_runtime.py`: scheduler ordering, concurrency, failure, cycle, and workflow rules.
- `tests/test_fods_enrichment.py`: schema/evidence/hash validation, cache poisoning/reuse, partial
  batch recovery, provider timeout/malformed data, and snapshot isolation.
- `tests/test_fods_research.py`, `tests/test_fods_phase2_plans.py`: Quick/Deep policy, ranking,
  query plans, and workflow plan validation.
- `tests/test_fods_benchmark.py`: blank annotations, scoring, and no-overwrite protection.
- `tests/test_fods_visualize.py`, `tests/test_fods_webapp.py`, and `tests/test_fods_tracing.py`:
  event-driven views and tracing.
- `tests/test_p<N>_*.py`: the original RLA milestone suite.
- `pyproject.toml`: src-layout packages and `rla`/`fods` console entry points.
- `.env.example`, `src/rla/config.py`, and `AGENTS.md`: configuration and environment behavior.

Use `.venv` tools on Windows. The supported invocation is `python -m fods.cli ...` from the
repository root (or the installed `fods` entry point), not `python -m src.fods.cli`.

## Verified status at handoff

- Branch: `codex/phase2-1-verification`.
- Latest commit: `48b5962` — `Complete FODS Phase 2 research runtime`.
- Verification: **721 tests passed**, Ruff/lint and formatting passed, source compilation passed,
  wheel contents and installed FODS CLI help passed. Full details are in the Phase 2.1 report.
- Bounded live OpenAlex reference discovery succeeded: two resolver tasks, five resolved reference
  records, a checksum-verified child snapshot, approximately 1.32 seconds elapsed.
- Local `ollama/qwen3:4b` was configured, but the Ollama endpoint timed out during its availability
  check. Live enrichment is therefore unverified. Gemini was not called; its use requires the
  explicit `RLA_FODS_ALLOW_GEMINI=1` opt-in, and its quota is limited.
- The fixed ten-query Quick/Deep relevance benchmark has no paired live runs or human labels.
  Retrieval quality must remain unclaimed until candidates are human-reviewed.
- A complete Quick/Deep collection can dispatch up to **230 source-query requests**. Budget review
  must precede launching those 20 runs. The current CLI has no retrieval-only mode; its regular
  workflow includes evidence selection, citation validation, and brief writing.
- Full-text retrieval and a calibrated semantic claim-support verifier are outside the verified
  implementation. The semantic support marker remains `unverified`.

## Operating constraints and invariants

1. Keep the user's fast-context goal: source acquisition and abstract context first; optional model
   extraction later.
2. Keep FODS as the sole scheduler. A model can propose a plan but cannot dispatch or bypass plan
   validation.
3. Keep citation validation as a hard prerequisite for the write task. A failed citation check
   must not produce a success-marked saved brief.
4. Keep provider source-reference edges separate from inferred concept edges.
5. Keep context snapshots immutable and validate their content hashes on reuse. Enrichment belongs
   in derived artifacts; reference discovery creates a child snapshot.
6. Do not report retrieval precision/recall without valid human labels and denominators. `uncertain`
   is not a binary relevance label.
7. Do not silently spend Gemini quota. Standard tests and fixture demos should remain offline.
8. Treat `data/corpus.json`, `data/extractions.jsonl`, and `data/concepts.json` as committed user
   data; do not regenerate/reformat them casually. The existing RLA corpus and extraction store
   were previously found inconsistent, so they are not a verified FODS context source.
9. Preserve existing user changes and commit/branch only when the user asks. The current worktree
   may contain ignored local run data and test scratch files.

## Suggested next direction for the master agent

First review the status and budget gates with the user. A sensible next measurable step is to make
the local Ollama enrichment smoke runnable by ensuring the model endpoint is available, then run one
paper batch and record accepted/rejected/cache outcomes. Separately, decide whether to add a
retrieval-only mode before starting the ten-query benchmark; this can remove answer/write work while
retaining FODS source scheduling and validation. Do not launch the paired live benchmark until the
user reviews the source-request budget and agrees to proceed.

When directing implementation work, give one bounded vertical task at a time, cite the relevant
acceptance criteria, require the exact tests to pass, and keep runtime behavior separate from
visualization presentation. This handoff is project context, not permission to call paid/limited
providers, run the 20 live benchmark runs, or make broad architectural rewrites.
