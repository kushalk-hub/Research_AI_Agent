# FODS Research Agent — Next-Phase Development Plan

**Planning baseline:** checkpoint `2026-11-01`, branch `codex/fods-mvp-acceptance`, HEAD `f533ae1`.  
**Sequence rule (owner decision revision):** the owner waived the human-review benchmark as a prerequisite for frontend development. The benchmark remains pending and unpassed; its human-review integrity requirements remain applicable if retrieval quality is evaluated. Frontend work may proceed now using labeled synthetic/demo fixtures. Phase 1 is no longer a sequencing blocker for Phases 3–6.

**Current redesign gate:** the owner has requested a complete FODS Research Studio redesign proposal and separate static prototype, with no production frontend rewrite until the owner reviews and approves them. Treat that design review as the immediate gate for the redesign; prior authorization for the initial shell does not supersede this explicit production-change boundary.

## Owner decision revision — 2026-11-01

The owner explicitly approved starting frontend development before human review is complete. This supersedes the phase-ordering prerequisite below, but does not turn blank benchmark sheets into results or constitute retrieval-quality acceptance. Preserve the paired/pooled source sheets, use synthetic fixtures for deterministic frontend work, retain the accepted backend and classic UI fallback, and keep browser/manual acceptance separate from automated tests.

## Phase 0 — Checkpoint and baseline preservation

### Work

1. Treat [`PROJECT_STATE.md`](PROJECT_STATE.md) as the snapshot of the inspected checkout and preserve the accepted backend commit `f533ae1` as the baseline.
2. Before later code changes, run `git status --short --branch`, `git rev-parse HEAD`, and `git log -8 --oneline --decorate`; record new work separately from existing documentation changes and `.pytest-tmp/` artifacts.
3. Preserve `benchmarks/paired_review_20261031.csv`, `benchmarks/pooled_review_20261031.csv`, `data/fods/` source contexts/enrichments, original schema-v1 graph, accepted CI artifact, and existing fixture artifacts. Make dated working copies before human annotation.
4. This was the original checkpoint boundary. It is superseded by the owner decision above, which authorizes scoped frontend implementation while retaining the recorded backend/data protections.

### Exit criteria

- Checkpoint and handoff documents are present and linked from README/documentation index.
- Accepted baseline, current worktree state, existing artifacts and known limitations are recorded.
- No application code, graph schema, review data, or accepted commit was modified by the checkpoint task.

## Phase 1 — Human-reviewed retrieval benchmark (blocking gate)

The current files are blank-label review sets, not evaluation results. Use actual human reviewers; do not ask an LLM/Mammoth evaluator to supply labels and call them human review.

### Step 1: approve the review protocol before full annotation

Project owner/reviewer decision required because no inspected document defines:

- Number/identity of reviewers and how identity will be recorded (neither paired nor pooled file has a structured reviewer-ID field).
- How independent judgments and disagreements are handled; available label values have no adjudication field.
- Whether `pooled_review_20261031.csv` is a coverage/union review aid only or must have a separately scored metric. The pooled schema has `quick_rank`/`deep_rank` but no `row_type`, `profile`, or common `rank`; `python -m fods.benchmark score` expects the paired schema. Do not feed the pooled sheet to that scorer. The Mammoth evaluator is model-assisted and not a human scoring path.
- A quantitative project acceptance threshold and comparison rule. No threshold is present in the inspected reports; do not invent one.

The existing label vocabulary and pooled/paired fields are defined in `benchmarks/README.md`, `benchmarks/retrieval_review_template.csv`, `benchmarks/paired_review_20261031.csv`, and `benchmarks/pooled_review_20261031.csv`. `reviewer_notes` / `notes` are free text, not a structured identity or consensus model. Until a structured field is approved, preserve reviewer identity in a separate adjudication ledger or an agreed notes convention; do not silently repurpose benchmark metadata.

### Step 2: create protected annotation copies

Keep the committed/collected source sheets unchanged. Create date-stamped copies, for example:

- `benchmarks/paired_review_human_YYYYMMDD.csv`
- `benchmarks/pooled_review_human_YYYYMMDD.csv`
- A separate reviewer/adjudication ledger if more than one human is involved.

Current denominators to reconcile against: paired = **650 rows** (200 Quick, 450 Deep); pooled = **450 rows**, 45 per query. Current labels are blank in both. Keep `query_id`, profile/rank and paper identity intact.

### Step 3: label the paired Quick/Deep rows

1. Review the title and supplied abstract/excerpt against the exact question in each row. Labels are `relevant`, `not_relevant`, or `uncertain`; use notes to explain borderline/insufficient evidence.
2. Do not treat an LLM score, search rank, citation marker, or paper title alone as an independent human judgment. Reviewers may open the supplied DOI/URL for context, but record the judgment basis and retain the frozen candidate row.
3. The same query-paper identity can occur in Quick and Deep. Use `paper_identity`/paper IDs/DOI to cross-reference and keep labels consistent for the same query-paper pair unless a reviewer records a reason for a different interpretation. A paper appearing in multiple queries receives a question-specific judgment.
4. Collector-level same-run duplicate observations are represented in fields such as `source_observation_count` and `duplicates_merged`; do not count them as separate relevance judgments. Do not merge possible preprint/published variants merely from similar titles; flag ambiguous identities for human adjudication.
5. Leave an unresolved item `uncertain`, not binary. Mark `judged_pool_complete=true` on every row in a query/profile group only after every candidate in that entire group has a binary label and the reviewer confirms pool completeness. Otherwise leave false.

### Step 4: review the pooled union sheet

Use the pooled file to inspect the 450 unique query-paper union and assess whether the paired sheets' Quick/Deep overlap and candidate coverage are represented consistently. Label its `reviewer_label` and `notes` only under the owner-approved protocol. Check `quick_rank`, `deep_rank`, `in_quick`, and `in_deep` against the paired rows. Do not label the entire pooled set by copying model judgments. The exact scoring/output mechanism for human pooled labels is an unresolved tool/protocol decision; report counts and reconciliation separately until a human-compatible scoring method is approved.

### Step 5: run the supported paired scorer and report limits

The existing scorer is `src/fods/benchmark.py`; it scores human-provided paired labels and never fills blanks. After annotation, use a new output filename (never overwrite the checked-in blank sheet or a prior metrics report):

```powershell
python -m fods.benchmark score `
  --input benchmarks/paired_review_human_YYYYMMDD.csv `
  --output benchmarks/paired_metrics_human_YYYYMMDD.json --k 5 10
```

Expected output: JSON with `quality_verdict`, per-query/profile and per-profile groups, review counts, relevant/uncertain counts, Precision@5/10 with reviewed denominators, and Recall@5/10 only for fully binary-labelled groups explicitly marked complete. It also reports retrieval/context coverage, source outcomes, latency, failed runs, selected evidence and citation-validation diagnostics. Include raw denominators beside averages and report incomplete/uncertain pools. Do not claim recall where its denominator is unavailable.

The collector command is already documented for regenerating a *new* blank review pack from saved logs; no collection or network calls are needed to review the current packs:

```powershell
python -m fods.benchmark collect --query-set benchmarks/retrieval_queries.json `
  --output benchmarks/paired_review_YYYYMMDD.csv $runLogs
```

The repository's two existing pack outputs are `benchmarks/paired_review_20261031.csv` and `benchmarks/pooled_review_20261031.csv`; the scorer's reproducible output is a dated JSON path. Do not overwrite existing files. Do not run `tools/mammoth_evaluator` as a human review tool; it uses an OpenRouter model decision client.

### Phase 1 acceptance criteria

- Review protocol, reviewer identity, disagreement handling, pooled-sheet role/scoring plan and quantitative pass threshold are explicitly approved and recorded.
- Human labels cover all 650 paired rows or an explicitly approved sampling/coverage design; any deviation is visible. Uncertain and unresolved identities are counted and explained.
- Paired metrics are generated by the existing scorer from a preserved dated annotation copy; scorer output and review file hashes are recorded.
- The 450 pooled labels (if retained as a required gate) are human-generated and reconciled to paired identities/ranks; no unsupported scorer output is reported.
- Metrics include coverage/denominators, incomplete pools, and limitations. Pass/fail is compared with the approved threshold; until then the benchmark remains pending.

**Exit:** only after these criteria are met may the frontend proposal's benchmark prerequisite be considered passed. If the approved threshold is not met, record that outcome and decide a corrective backend/retrieval experiment before moving to redesign.

## Phase 2 — Existing frontend baseline and integration verification

This phase can run as read-only verification alongside Phase 1. It is not a redesign.

### Procedure

1. Confirm branch/HEAD/worktree again and use an isolated test data root or `.venv` test fixtures.
2. Start `python -m fods.cli serve --host 127.0.0.1 --port 8765`; open `http://127.0.0.1:8765/`. If Windows denies loopback, record the error and stop; do not alter security settings.
3. If reachable, use deterministic fixture mode and a new brief name. Record actual submit, status, SSE event appearance, task selection, DAG/queue/state inspector, evidence, citation-to-card navigation, brief link, history, and replay behavior.
4. Exercise FODS Lab cycle rejection, bounded source failure, citation guard, and FIFO-vs-priority comparison where feasible. Mark manual actions separately from automated backend/API test evidence.
5. Capture screenshots only from the running application. Save timestamped originals under a documented checkpoint artifact directory; record which run/route each image shows. No screenshot exists at this checkpoint.
6. If browser launch remains blocked, retain API test evidence as API-only and use existing CI HTML/JSONL/brief artifacts as an offline fallback. Do not call that a completed browser test.

### Phase 2 acceptance criteria

- Every journey step above is marked passed, failed, or environment-blocked with evidence/commands.
- At least one actual deterministic run is tied to its own trace and brief; replay is identified as replay.
- If browser evidence is blocked, limitation and fallback are explicit; no fabricated screenshot or complete browser claim.
- Existing API/SSE integration tests remain green in the designated test run; manual visual validation is separately recorded.

## Phase 3 — Proposed frontend application shell

**Prerequisite:** owner authorization is recorded above. Human-review Phase 1 is not a prerequisite, but remains unpassed. Keep the current workbench available until the replacement shell passes its gate.

### Implementation scope

- Build Chat, Trace, and FODS Visualizer views with persistent run/session history, shared selected-run state, and visible LIVE/SIMULATION/REPLAY provenance.
- Follow `docs/design/frontend_design_research.md`; keep event/runtime state authoritative and browser navigation/display derived from the selected run.
- Preserve current backend API, SSE and old JSONL compatibility. Do not implement another scheduler or readiness calculation in JavaScript.
- Clearly distinguish deterministic simulation from live source execution and replay.

### Exit criteria

- All primary views and history navigation exist and operate over the same run identity/events.
- A researcher can begin a run, inspect current status, choose a saved context when supported, and return to a prior run without changing task execution.
- Model/provider attribution is sourced from recorded metadata, and unknown values remain unknown.
- API/SSE, UI unit/integration tests and a recorded browser walkthrough demonstrate the shell; source files existing alone do not pass the gate.

## Phase 4 — Event-backed FODS Visualizer

Give the visualizer its own acceptance milestone. If the required event identity/correlation fields are missing, add a versioned/compatible event-contract adapter before UI polish; never invent execution state to make an animation look complete.

| Concept | Required behavior | Evidence required to pass |
|---|---|---|
| DAG | Show real tasks, directed dependency edges, validation/readiness and state. | Compare visible nodes/edges/state with the accepted plan and event trace. |
| Queue/priority | Show actual ready queue order and enqueue/dequeue events; explain fixed priority and FIFO tie order. | Same deterministic plan under FIFO and priority, with trace-derived order. |
| Workers | Show actual occupied slots and overlapping task intervals, derived from events. | Event timestamps/tasks reconcile with each occupied slot; no synthetic workers. |
| Task map | Show state by task ID and transitions. | Selection/state agree with trace. |
| Stack/recovery | Show per-task pushes/pops, failures, retry/blocked/cancel decisions. | Each displayed operation has a source event and task ID. |
| Event log | Inspect recorded event sequence with event details. | Sequence and payload match persisted JSONL. |

Required interaction: play, pause, step forward/backward through the **recorded view**, reset, playback speed, follow live execution where supported, select task and synchronize its DAG node/queue/state/trace details, and compare FIFO/priority on identical deterministic inputs. Rewinding a view must never claim to undo runtime side effects. Explain projections if the event contract does not contain enough data for a state.

### Exit criteria

- Every required structure is visible, linked to actual events, and assessor-understandable.
- Every required control is tested; event stepping/reset work on saved deterministic traces, live-follow behavior is separately labeled.
- Task selection synchronizes related panels; FIFO/priority uses identical input plans.
- Automated tests and recorded manual artifacts show no fabricated task/worker/event states.

## Phase 5 — Trace and evidence inspection

### Implementation scope

- Present time-ordered task/model/tool/source/context/output activity with correlation only when the event contract supports it.
- Show event payloads, source/model attribution, failures, retry/recovery reasons, and actual durations without exposing secrets.
- Add an evidence/citation drawer or equivalent synchronized inspector: citation → selected card → paper record and exact stored excerpt/locator.
- Label citation-ID validity separately from semantic support; do not imply entailment review unless separately evaluated by humans.

### Exit criteria

- Trace rows map to persisted event IDs/sequence and parent task when recorded; uncorrelated activity is explicitly shown as uncorrelated.
- Selecting a citation navigates to its evidence and paper; source excerpts match saved context.
- Provider/model provenance agrees with run metadata; no fallback/model is reported unless recorded.
- Invalid citation and failed output states are visible and do not show a success brief.
- Security/redaction and existing API/JSONL compatibility tests pass.

## Phase 6 — End-to-end frontend acceptance

Run and separately report automated and manual checks for:

1. Deterministic simulation.
2. Live retrieval where providers and network are available (otherwise mark environment-blocked, not passed).
3. Unavailable provider or failed source.
4. Cycle rejection before tool calls.
5. FIFO vs priority on identical deterministic plans.
6. Evidence and citation inspection.
7. Context-reuse follow-up with no new acquisition unless refresh is selected.
8. Replay with no new source/model calls.

### Phase 6 acceptance criteria

- The research question-to-brief journey works end to end in the running frontend.
- All primary views are implemented and integrated with API/SSE.
- Visualizer shows actual DAG, scheduler, worker, task-state, stack and event data; task selection synchronizes panels; recorded event stepping/replay works.
- Evidence navigation, accurate model/provenance attribution, and inspectable error states work.
- Automated tests and manual results are both recorded. At least one real screenshot comes from the running application, accompanied by its run ID/trace/brief and clear execution mode.
- Live-only checks blocked by credentials/network are identified as such and do not invalidate deterministic coverage or get called passed.

## Overall project completion criteria

Do not call the whole project complete until:

- Backend acceptance remains green on the current target branch.
- Human-reviewed retrieval benchmark has approved protocol, traceable labels, reproducible metrics, and a pre-approved pass threshold that is met.
- The final frontend shell, trace/evidence view, and event-backed visualizer pass Phases 3–6 with tests and real recorded demonstration evidence.
- Live-provider and Windows/browser limitations are documented, and replay is not presented as fresh execution.
- Every acceptance claim can be tied to a test, CI run, artifact, screenshot, or human-review report.

No PPT/slides are in this plan. Presentation material is a later task after the implementation and demo evidence are reviewed.
