# FODS Research Agent Frontend Design Research

**Status:** Design specification for review; implementation has not started
**Research date:** 2026-10-29
**Scope:** Frontend experience and the minimum backend/event changes needed to support it

## 1. Executive summary

The product should tell one continuous story: a researcher asks a question, watches the FODS runtime turn it into independent source tasks, sees evidence arrive and become reusable context, then receives an answer whose citations can be inspected. The core product is a research chat with three primary views: **Chat**, **Trace**, and **FODS Visualizer**. A persistent run/session sidebar makes prior work discoverable. These views must read the same run and event stream so the answer, source evidence, scheduler state, and visualization cannot contradict each other.

The existing implementation already has the important runtime foundation: a validated task DAG, runtime-owned queue and readiness scheduling, parallel source work, persisted context, evidence selection, citation checks, replay, and an event stream. A real live trace has recorded Qwen/Ollama planning and Gemini answering. The main gap is product presentation and a few observability contracts: the current five-tab workbench exposes useful internals, but it does not yet feel like one chat-led research application; the FODS structures are summarized rather than shown as a legible, step-able visual model; and event records need stronger correlation and versioning for a polished trace.

The design should preserve a fast first research pass. Start answering as soon as the configured source quorum has produced enough usable evidence; allow remaining tasks to finish in the background and mark the answer provisional or final according to the selected policy. Reuse stored context for follow-up questions without searching again unless the user explicitly requests refresh. Keep expensive optional enrichment out of the blocking path. The UI should show actual provider/model attribution and honest run state, including partial results and failures.

The proposed visual proof is not an animation detached from execution. Each node, queue item, stack operation, tool call, evidence record, and answer state must be backed by a recorded runtime event or be explicitly labeled as an explanatory projection. Three playback modes must be visually distinct: live execution, deterministic simulation, and replay.

## 2. Scope and research method

This document is an implementation-ready frontend design specification based on the current repository and the official DeepSeek Harness references listed in §15. It distinguishes **Observed** behavior in the repository or reference material, **Inference** about design implications, and **Proposal** for this project. DeepSeek Harness is used as a reference for separating chat from execution trajectory and for treating a typed event/session log as the source of truth; its product architecture is not assumed to be identical to FODS.

The Firecrawl website-design-clone workflow was attempted for the official reference site. Firecrawl returned an account-banned authorization error, so no Firecrawl capture, scrape, screenshot, or generated asset was used. The official DeepSeek product page was inspected visually in a browser, and its official repository and documentation were read. The documentation root did not expose readable page text through the web reader; the specific official quickstart and subsystem pages were readable. The product page uses illustrative product panels and is not evidence that every depicted control is part of a running application.

The repository review was read-only for application code. No code, dependency, environment, key, runtime, or data changes were made for this report. The only intended deliverable is this document.

## 3. Current implementation inventory

### Existing frontend

`src/fods/web/index.html`, `app.js`, and `styles.css` provide a local browser workbench with five tabs: Overview, Execution, FODS Lab, Evidence & answer, and Runs & replay. Overview accepts a topic and question, execution mode, planner, concurrency, source count, FIFO/priority mode, output filename, and context-reuse choice. It shows configured provider names and whether Gemini is configured/opted in; the key itself is not sent to the browser.

Execution renders a dependency DAG by readiness level, a chronological event table, and a selected task/event inspector. Its timeline pairs `task_started` with terminal task events; it is not yet a model/tool/source waterfall. FODS Lab shows dependency/readiness summaries, queue operations, task state, stack push/pop and recovery, cycle/failure/citation demos, and FIFO-versus-priority comparisons from deterministic runs. These are useful demonstrations of real runtime behavior, but the lab is a collection of panels rather than a guided animated model with a persistent selection, playback controls, and synchronized event cursor.

Evidence & answer shows paper metadata, abstracts, source names, DOI/URL, selected evidence, answer text, citation validation, and the saved brief. Citation markers navigate/scroll to the related evidence card; there is no citation detail drawer. Runs & replay lists run status, mode, topic, completed model identities, duration, artifacts, and replayable event logs. The run form is not a durable multi-turn chat: each submitted question starts a run against selected/reused topic context.

### Runtime and data already available

The local Python `ThreadingHTTPServer` serves JSON APIs and SSE from `src/fods/webapp.py`. It has health/config/history/context/run/event/brief/visualization endpoints plus run creation, replay, and deletion. SSE streams runtime events (not model text tokens), supports `Last-Event-ID`/`after`, and the browser never receives credentials. JSONL logs, context snapshots, and briefs are persisted under `data/fods/`. The history view is capped at 100 records.

The FODS runtime owns plan validation, cycle rejection, task readiness, FIFO/priority queue behavior, worker execution, bounded retry/recovery, and event emission. Source tasks can run concurrently; a live run uses a two-source quorum and may cancel optional work after the quorum is met. The planner produces a structured plan; this is not currently represented as native model function-call events. FODS context currently emphasizes paper metadata and abstracts, not full-text extraction or a complete concept graph. The standalone RLA package has richer extraction/graph stages, but the FODS first slice does not execute those stages.

Model and tool lifecycle events exist, as do plan/task/queue/stack/context/evidence/answer/citation/brief events. The generic event envelope is `seq`, `kind`, `message`, `payload`, and `timestamp`; it has no explicit schema version and model/tool activity identifiers are not uniformly correlated. Tool events contain useful arguments, parent activity, attempt, duration, output summary, and failure details. Model events identify activity, stage, provider/model, parent task, stack, fallback count, and output summary. Answer citation checking validates that markers refer to selected evidence IDs; it does not prove that each sentence is semantically entailed by its cited source.

The current UI can show configured model availability and actual completed model identities. Gemini answer use requires a configured key and explicit `RLA_FODS_ALLOW_GEMINI=1` opt-in; local Ollama is available. Runs may use deterministic answer behavior when Gemini is unavailable or not opted in. Fresh-source retrieval is available through the API/CLI but is not exposed in the run form. The backend already blocks a brief from being reported saved when citation validation fails and confines output filenames to the approved workspace.

## 4. DeepSeek Harness reference analysis

The official DeepSeek Harness product page visually presents a chat-like application alongside developer-oriented execution tracing. The trace illustration uses time-ordered lanes (including input, model, and tools) and compact event details, which supports the idea that user-facing conversation and technical trajectory can coexist as distinct views. Since these are marketing illustrations, the report borrows the information hierarchy rather than asserting exact interaction behavior. [R1](#r1)

The official docs describe a layered web client, with authoritative host/session state and persistence separated from transport, client models, UI adapters, conversation/data assembly, and rendering/composition. This is a useful boundary: FODS should keep its runtime and persisted event log authoritative, expose a stable transport, and make Chat, Trace, and FODS Visualizer projections of that shared state. [R5](#r5)

The session reference describes an append-only typed event log as source of truth, with message history derived from events. It calls out sequence continuity, lossless JSON, turn/step boundaries, and tool-call/result correlation. The conversation reference similarly favors target-neutral event assembly and separate Chat and Trajectory projections. FODS already has JSONL events and replay, so the primary adaptation is to firm up event identities/versioning and render synchronized projections; it is not necessary to replace the scheduler or adopt the other system's storage model wholesale. [R4](#r4), [R7](#r7)

The quickstart is useful as a reference for onboarding into a working client, but its workspace-selection requirement is specific to that project and should not be copied into FODS without a product need. The core reference reinforces the separation of session log, prompt assembly, tool registry, agent types, and execution loop. [R3](#r3), [R6](#r6)

## 5. Design principles and visual direction

1. **One research run, several synchronized views.** Chat, Trace, and FODS Visualizer consume a shared run store and event cursor.
2. **Show the real runtime.** A visual state is derived from actual events; illustrative/demo events carry a simulation or replay badge.
3. **Fast first useful answer.** Make quorum and context reuse visible. Let users choose when to wait for optional enrichment.
4. **Evidence before polish.** Citation and source provenance remain one click away from every claim.
5. **Progressive detail.** Chat is readable by default; technical detail is available without flooding the main answer.
6. **Honest model attribution.** Show the model that completed each operation, including fallback or deterministic behavior.
7. **Recoverable sessions.** Persist run events and context references, with explicit freshness and source provenance.
8. **Accessible motion.** Animation is optional, pausable, keyboard-operable, and reduced-motion aware.

**Proposed visual direction:** a calm light workspace for reading and writing, with a dark high-contrast FODS canvas for the runtime visualizer. Use restrained blue for selected/active state, teal for completed evidence-backed work, amber for waiting/retry/partial, and red for rejected/failed. Do not encode status with color alone; pair color with text and icon/shape. Proposed typography: system sans for UI, monospace for IDs and payloads. Proposed spacing scale: 4/8/12/16/24/32 px; panel borders and subtle backgrounds should define structure more than shadows. These are design proposals, not colors/tokens measured from the reference site.

## 6. Information architecture

### Primary destinations

- **Chat** — research question, plan summary, live progress, answer, follow-up questions, and evidence citations.
- **Trace** — chronological/model-tool-source/task waterfall and event details for one run.
- **FODS Visualizer** — interactive DAG, ready queue, dependency/readiness state, task map, stack/recovery history, and scheduler teaching controls.
- **Run history** — a persistent sidebar list grouped by recent date/project, with status, topic title, and mode badge. Selecting a run restores its Chat and allows Trace/Visualizer inspection.

The selected run is the central navigation state. Chat/Trace/Visualizer tabs switch projections of that run; they must not start separate copies of the workflow. A “New research” action starts a new conversation/run. A research conversation may contain several runs, where follow-up turns reuse a named context snapshot or deliberately refresh sources.

### Context and freshness model

Show a compact context chip near the composer, e.g. `Context: 12 papers · 8 abstracts · saved 2 min ago`, with an inspect action. Distinguish **reuse context**, **refresh sources**, and **add sources**. Reuse should be the default for a follow-up question inside a research conversation, with a visible source snapshot/version. Refresh is a deliberate action and starts a retrieval stage. Never imply that a follow-up question triggered new source calls when it reused stored context.

### Global layout

Desktop: left navigation/history rail (240–280 px), central workspace (flexible, minimum 600 px), optional right inspector/drawer (320–400 px). Chat can use the central width; trace and visualizer use the full central canvas. On narrower screens, history becomes a drawer and evidence/detail becomes an overlay. Keep global model/key configuration out of the main conversation; expose safe status in settings/run metadata.

## 7. Screen specifications

### Chat

The conversation begins with the research title/topic, a concise run configuration row, and the submitted question. As the run proceeds, show a collapsible plan card with task count, dependencies, current concurrency, source quorum, and actual planner model. A compact progress row states completed/running/queued/failed tasks and elapsed time. Evidence cards appear as source tasks finish; do not wait for all optional sources to finish before showing the configured quorum result.

The answer panel contains a short status label (`Draft`, `Validated`, `Partial evidence`, `Needs review`), answer text, citation markers, source coverage summary, actual answering model, and actions to copy/export/open Trace. Show citation validation outcome separately from semantic support: for now label it “Citation IDs verified,” not “claims proven.” A failed citation check must render a failed/not-saved state and the recovery decision; it must never show a success toast or a valid saved-brief link.

The composer supports a follow-up question, context reuse by default within the same conversation, and a clearly labeled “Refresh sources” choice. While a run is active, allow cancel if supported and preserve the event log. Provide a stop/wait distinction for quorum work and optional remaining enrichment.

### Citation and evidence drawer

Clicking `[P3]` opens a right drawer anchored to paper P3, preserving scroll and answer position. Show title, authors if available, year, venue, source, DOI/URL, abstract, selected evidence excerpt, retrieval score/selection reason if available, and the exact claim sentence that cited it. Make the external source link explicit. Include “open paper record” and “close” actions. On current data, avoid inventing full-text snippets; say “Abstract” when the evidence is abstract-derived.

### Trace

Render a time ruler and aligned lanes: **Run/plan**, **FODS tasks**, **Models**, **Tools**, **Sources**, **Context/evidence**, and **Answer/output**. Each operation is a duration bar where start and end events exist; point events such as queue updates are markers. Display waiting/queued spans separately from execution spans. Clicking any event/bar opens a details panel with timestamp, duration, event ID, parent/correlation IDs, provider/model, arguments/output summary, retry count, and error/recovery where applicable. Provide filters for lane, status, task, provider/model, and text; retain a chronological event list for accessibility and precision.

The trace header labels its provenance: `LIVE`, `SIMULATION`, or `REPLAY`. Replay includes the original run ID and replay time; simulation carries a deterministic seed/scenario. Replay must never be presented as proof of live concurrent execution. Show source task overlap only when timestamps from the live log demonstrate overlap.

### FODS Visualizer

Use three synchronized regions. **Dependency graph:** nodes are tasks, directed edges encode dependencies, and state is visibly queued/ready/running/completed/failed/blocked/cancelled. **Scheduler panel:** ready queue order, priority/FIFO policy, worker slots, and dequeue/dispatch decisions. **Runtime state panel:** task-state map and stack/recovery operations, shown as explicit event-backed state transitions. A shared selected task highlights its graph node, queue row, related trace events, and evidence output.

Teaching controls support play/pause, step forward/backward through recorded events, reset to initial state, speed, and “follow live.” For live runs, stepping backward is a view over recorded events, not a rollback of runtime execution. Provide `Show scheduler comparison` to run or load the existing deterministic FIFO/priority examples; display identical task inputs, different dequeue order, and resulting measured order/timings. Cycle rejection should show the invalid edge and validation event before any tool call. Failure recovery should show bounded attempts and the recovery decision. All teaching scenarios carry a simulation badge.

### Runs and replay

The run history row shows topic, latest question, date, source count, status, duration, and actual model identities. Run detail offers Chat, Trace, and Visualizer. Replay uses saved events and makes no source/model calls. Indicate unavailable/corrupt logs clearly and preserve the original record. Run deletion should state its effect on associated saved artifacts/context before confirmation; this is a future product decision, not needed for the first slice.

## 8. Text wireframes

### Chat with citation drawer open

```text
┌──────────────┬──────────────────────────────────────────┬──────────────────────┐
│ FODS         │ Chat   Trace   FODS Visualizer            │ Evidence             │
│ + New        │ Topic: Efficient graph retrieval          │ [P3] Paper title      │
│ Recent runs  │ Run: LIVE · 2/3 sources · 14.8 s          │ Authors · Year       │
│ ● Graph RAG  │ You: What tradeoffs do recent papers find?│ DOI / Source link    │
│ ○ RAG eval   │ Plan ▾  4 tasks · 2 parallel · Qwen       │ Abstract              │
│              │ Evidence arriving: [P1] [P2] [P3]         │ Selected excerpt     │
│              │ Answer · Citation IDs verified            │ Cited sentence       │
│              │ ... [P3] ...                               │ Open paper ↗          │
│              │ Answered by Gemini ...                    │                      │
│              │ [Ask a follow-up...       Reuse context]   │                      │
└──────────────┴──────────────────────────────────────────┴──────────────────────┘
```

### Trace

```text
┌──────────────┬──────────────────────────────────────────────────────────────┐
│ Run history  │ TRACE  LIVE · run id · 20.4 s · 2/3 quorum · filters         │
│              │ time ─────────────────────────────────────────────────────── │
│              │ Plan       [Qwen planner]                                    │
│              │ FODS tasks [source A ─────] [source B ───] [source C canceled]│
│              │ Tools        [search] [fetch/normalize]                      │
│              │ Context                         [snapshot] [select evidence] │
│              │ Answer                                       [Gemini answer]  │
│              │ Event list: timestamp | lane | event | status                 │
│              │ Selected event details in bottom/right inspector              │
└──────────────┴──────────────────────────────────────────────────────────────┘
```

### FODS Visualizer

```text
┌──────────────┬──────────────────────────────────────────────────────────────┐
│ Runs         │ FODS VISUALIZER  SIMULATION · FIFO · Play / Step / Reset      │
│              ├───────────────────────────────────────┬──────────────────────┤
│              │ DAG                                   │ Ready queue / workers│
│              │ [plan] → [source A] ─┐                │ 1. A  running        │
│              │          [source B] ─┼→ [context]     │ 2. B  running        │
│              │          [source C] ─┘     ↓          │ 3. C  ready          │
│              │                    [answer]           ├──────────────────────┤
│              │ highlighted task follows event cursor │ State / stack events │
│              └───────────────────────────────────────┴──────────────────────┘
└──────────────┴──────────────────────────────────────────────────────────────┘
```

On a narrow display, replace the left rail with a menu, stack the primary view and controls, and open evidence/inspectors as full-height overlays. Preserve the same event ordering and provenance labels.

## 9. Interaction flows

### First question

1. Researcher enters a topic/question and selects or accepts the default source/context policy.
2. UI creates the run and immediately displays the run ID, mode, and event-backed startup state.
3. Planner result appears as a plan card. If validation repairs or rejects it, show that event and reason.
4. Validated independent source tasks enter FODS readiness/queue visualization; actual concurrent starts occupy worker slots.
5. Each source result is normalized, deduplicated, persisted with provenance, then contributes to the reusable context snapshot. Progress updates incrementally.
6. At quorum, evidence selection and answer generation proceed. Remaining optional sources may continue according to policy.
7. Citation ID validation gates brief save. Only after successful validation and `brief_saved` show a successful saved artifact.

### Follow-up

1. Researcher asks a question in the same conversation.
2. UI clearly states it will reuse a named context snapshot, including age and paper count.
3. Retrieval selects relevant stored evidence and answers; no source acquisition events should appear unless refresh is requested.
4. New answer citations open the same evidence drawer; the trace distinguishes context reuse from fresh acquisition.

### Inspect and teach

Selecting a task in the visualizer synchronizes graph, queue, trace and source output. Selecting a citation synchronizes answer sentence and evidence. A simulated scheduler demo exposes seed, policy, and scenario and records its own event stream; it must not silently alter a live run. Replay displays the exact stored sequence and allows event stepping without invoking models or sources.

## 10. Runtime event-to-UI mapping

| Runtime event/data | UI projection | Current support / gap |
|---|---|---|
| `run_started`, mode/run ID | run header, sidebar status | Available; persist visible provenance label |
| `plan_received`, `plan_repaired`, `plan_validated`, `plan_rejected` | plan card, DAG, validation/rejection explanation | Available; show structured errors and task/edge selection |
| `task_ready`, `queue_updated`, `task_dequeued` | ready queue and scheduler animation | Available; normalize queue snapshot/order fields for deterministic stepping |
| `dependency_updated` | prerequisite counts and readiness | Available; make dependency IDs and edge changes inspectable |
| `task_started/completed/failed/retry/blocked/cancelled` | DAG state, task spans, counts | Available; correlation and timestamps should be normalized |
| `tool_call_*` | Trace tool lane and inspector | Available; add stable call ID and schema version; redact secrets |
| `model_call_*` | Trace model lane and actual attribution | Available; add stable activity/correlation IDs and token/timing data only if provider supplies it |
| source results / `partial_source_set` | evidence arrival and quorum banner | Available; expose per-source task/provenance and explicit partial reason |
| `context_ready` | reusable snapshot chip and details | Available; show snapshot identity/freshness; avoid implying full text if abstract-only |
| `evidence_selected` | cited paper / evidence card | Available; add excerpt locator and selection rationale where supported |
| `answer_ready`, `citation_validation` | answer state / validation panel | Available; distinguish ID validation from semantic claim support |
| `brief_saved` | export link/toast | Available; success must follow valid validation only |
| `stack_push/pop`, `recovery_decision` | runtime state and recovery lane | Available; include stable operation ID and before/after summary |

Minimum event-contract additions recommended before visualizer polish: `schema_version`; stable `event_id`; `run_id`; `turn_id`; `task_id`; `activity_id`; `parent_activity_id` or `causation_id`; explicit `started_at`/`ended_at` for spans or a consistent start/end event pair; and provenance `execution_kind` (`live`, `simulation`, `replay`). Add provider/model fields only where known and report unknown accurately. Preserve old JSONL compatibility through a reader adapter/default version. Avoid serializing API keys or sensitive full prompts by default.

## 11. Present-versus-desired gap matrix

Priority: **P0** needed for the coherent core demo; **P1** needed to make the architecture inspectable and robust; **P2** polish or future research depth.

| Area | Present | Desired | Priority / dependency |
|---|---|---|---|
| Product navigation | Five workbench tabs | Chat, Trace, FODS Visualizer plus run/session history | P0; frontend restructure |
| Research conversation | One run form; topic context reuse | Multi-turn research conversation with explicit context snapshot | P0; run/session association |
| Source execution | Runtime DAG, queue, concurrency, quorum | Visible live plan, queue and task state with actual timing | P0; stable task event projection |
| Evidence and citations | Cards and scroll-to-paper | Click citation opens evidence drawer with cited sentence and provenance | P0; answer-to-evidence mapping |
| Answer persistence | Validated citation IDs gate brief | Explicit validation state and save confirmation only after persistence | P0; retain existing safety behavior |
| Trace | Chronological event table and limited task timeline | Correlated waterfall for tasks/models/tools/sources/context/output | P0/P1; event identity/correlation |
| FODS visualizer | Summary panels and deterministic comparisons | Synchronized, event-steppable graph/queue/state/stack | P0 demo / P1 reusable component; normalize queue snapshots |
| Modes | Live and deterministic/replay capabilities | Unambiguous LIVE/SIMULATION/REPLAY labeling everywhere | P0; execution provenance in run/event data |
| Replay | Stored JSONL replay exists | Step/replay without external calls; original run attribution | P0; event player and replay provenance |
| Failure teaching | Cycle/failure/citation demos exist | Guided scenarios, visible bounded retries and recovery | P1; reusable scenario definitions |
| Model use | Config model panel and actual completed models in history | Per-operation actual attribution and fallback explanation | P0; map lifecycle event IDs |
| Context speed | Snapshot reuse; quorum; optional enrichment cancellation | Fast useful answer with visible reuse/quorum policy and elapsed stages | P0; instrument stage durations; no algorithm rewrite assumed |
| Freshness | API/CLI option not form | User can choose reuse, refresh, or add sources | P1; UI/API control parity |
| Semantic support | Citation marker membership check | Claim-to-evidence review or semantic verification, honestly labeled | P2 research feature; evaluation design first |
| Full-text/concept graph | FODS first slice uses metadata/abstracts | Optional deeper extraction/visual concept map | P2; latency, source rights/access and storage study |
| Accessibility | Basic browser UI | Keyboard-first event inspect/step, labels, reduced motion | P1; frontend work |

## 12. Backend and research implications

The frontend can be delivered mostly by consuming existing run APIs and event streams. Keep the FODS scheduler as sole authority for validation, readiness, and queue decisions. The visualizer must render those decisions, not reimplement them in browser code. Add a small event normalization layer so the UI can group events into task/activity spans and load older logs.

For lower perceived latency, emit stage timestamps and expose quorum policy/state explicitly. Render evidence incrementally when persisted, then begin answer work as soon as the configured quorum and minimum evidence conditions are satisfied. Do not block the first answer on optional full-text extraction, graph enrichment, or all source candidates. Schedule enrichment as a follow-on activity whose completion updates the reusable context version. A question using the prior snapshot should remain usable while a new snapshot is being built.

The context model should identify snapshot ID, topic/query fingerprint, creation time, sources, paper count, abstract/full-text coverage, content hash, and parent snapshot when refreshed. This supports reproducibility and avoids hidden context mutation. Deduplication should preserve canonical paper identity and all source provenance. Evidence items should link to paper ID, extraction/snapshot version, and answer citation ID.

Semantic citation support is a separate research capability. The current “allowed citation ID” check is a useful integrity gate but cannot establish entailment. If pursued, make it an optional verifier with a disclosed method, per-claim evidence mapping, failure behavior, and evaluation set; never relabel ID integrity as proof of factual correctness.

## 13. Prioritized implementation roadmap

1. **P0 — App shell and run navigation:** left history rail, selected run/conversation header, Chat/Trace/FODS Visualizer destinations; keep current backend API compatibility.
2. **P0 — Chat vertical slice:** question composer, plan/progress, incremental evidence, answer/status/model, cited evidence drawer, context reuse chip.
3. **P0 — Provenance and run status:** display live/simulation/replay consistently; actual planner/answer model; quorum and partial-result state; safe brief-save result.
4. **P0 — Trace projection:** chronological event list plus aligned task/model/tool/source spans, synchronized selection, useful filters. Read current logs first; add only minimal event-normalization fields.
5. **P0 demo — FODS visualizer:** DAG, readiness queue, worker state, stack/recovery, shared event cursor, play/pause/step/reset; show existing deterministic FIFO/priority, cycle, failure, citation scenarios with simulation labels.
6. **P1 — Session/context polish:** durable conversation-to-run relationship, named context snapshots, fresh/add-source affordances, log compatibility and reconnect behavior.
7. **P1 — Accessibility and resilience:** keyboard operation, reduced motion, narrow layout, SSE reconnect/duplicate handling, corrupt log messages.
8. **P2 — Research enrichment:** optional full text, concept graph, semantic citation review, and deeper comparative evaluation only after latency and source coverage are measured.

The critical path for an early demo is items 1–5, using the existing runtime and deterministic scenarios. Do not start with a broad rewrite of the RLA pipeline; this design does not require one.

## 14. Acceptance criteria

1. A researcher can create a run from Chat and immediately see whether it is live, simulated, or replayed.
2. Plan validation and cycle rejection are visible before any dependent source/tool execution.
3. Independent source tasks appear in the runtime-produced DAG and queue; overlapping live spans are based on actual timestamps.
4. Source results become visible and persist with paper metadata, abstract, canonical identity, and source provenance.
5. The context chip identifies the reused snapshot and coverage; a follow-up can run without new acquisition.
6. The answer displays the actual answering provider/model or states deterministic/unknown accurately.
7. Clicking a citation opens the corresponding evidence drawer and preserves the answer position.
8. Citation ID validation failure is visibly a failure, does not claim a saved brief, and shows the recovery action.
9. Trace lanes and event list derive from the same persisted event log; selecting an event synchronizes relevant panels.
10. Tool/model calls correlate to their parent task/turn and show bounded duration/status without exposing credentials.
11. FODS Visualizer shows runtime queue order, task states and dependencies; the browser does not decide scheduler order.
12. Step, pause, and reset operate on a simulation or recorded event view; live execution is not rolled back by visual stepping.
13. FIFO and priority comparison uses the same deterministic tasks and labels its result as simulation.
14. Cycle rejection, bounded retry/recovery, partial quorum, and citation failure are demonstrable scenarios.
15. Replay performs no source/model calls and is visibly distinct from live execution.
16. Saved brief success appears only after citation validation passes and `brief_saved` is recorded.
17. Core navigation and inspection work with keyboard; reduced-motion preference disables nonessential animation.

## 15. Source register

All DeepSeek sources below are official first-party pages/repository material. Reference pages were consulted on 2026-10-29.

- <a id="r1"></a>**R1 — Product page, visually inspected.** [DeepSeek Harness](https://www.deepseek.com/en/harness/). Used for the high-level coexistence of chat and developer trace presentation. Visual panels are illustrative, not treated as verified interaction behavior.
- <a id="r2"></a>**R2 — Official source repository.** [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness). Used to verify project identity and official documentation links.
- <a id="r3"></a>**R3 — Official quickstart.** [Quickstart](https://deepseek-harness.github.io/deepseek-harness/en/guide/quickstart). Used as a reference for entry flow; no workspace-selection requirement is assumed for FODS.
- <a id="r4"></a>**R4 — Official session subsystem.** [Session](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/session). Used for append-only event log, derived history, sequence/event identity, and tool call/result concepts.
- <a id="r5"></a>**R5 — Official web-client subsystem.** [Web Client](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/web-client). Used for layered state/transport/client/UI boundaries and shared projections.
- <a id="r6"></a>**R6 — Official core subsystem.** [Core](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/core). Used for the separation of session, prompt assembly, tool registry, agent execution and loop.
- <a id="r7"></a>**R7 — Official conversation assembly source.** [Conversation subsystem source](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/conversation.md). Used for target-neutral event assembly and separate chat/trajectory projections.
- <a id="r8"></a>**R8 — Official documentation root.** [DeepSeek Harness documentation](https://deepseek-harness.github.io/deepseek-harness/). Consulted for navigation; the web reader did not return readable body text for the root page.

Repository sources inspected for current-state claims include `src/fods/web/index.html`, `src/fods/web/app.js`, `src/fods/web/styles.css`, `src/fods/webapp.py`, `src/fods/events.py`, `src/fods/runtime.py`, `src/fods/tools.py`, relevant FODS tests, and persisted sample event logs. These are local evidence, not external design references.

## 16. Open questions for design approval

1. Should a conversation contain multiple research runs/turns from the first demo, or should the demo use one run with a context-reuse follow-up and defer persistent chat threading?
2. At quorum, should the first answer be marked `Draft/Partial` while optional sources continue, or should answering wait until all requested sources complete? The speed goal favors quorum-first with honest status.
3. Which source count and concurrency should be the default demo setting given observed API quotas and local machine capacity?
4. Should context snapshots be immutable with explicit refresh-created versions? This is recommended for reproducibility.
5. Is the demo expected to include actual web/source execution only, or should deterministic simulation also be a first-class presentation path for scheduler comparisons?
6. Should the answer exporter remain a named file in the approved workspace, and which format is required for the presentation (Markdown is already supported)?
7. Which visual style is preferred for the FODS canvas: dark technical canvas beside a light research workspace, or one unified light theme?
