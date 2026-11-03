# FODS Research Studio — UX Redesign Proposal

**Status:** Approved design direction; production implementation authorized by the owner on 2026-11-01. The prototype remains a visual reference and is not production functionality evidence.  
**Prototype:** [`design/prototypes/fods-research-studio/index.html`](../../design/prototypes/fods-research-studio/index.html)  
**Companion acceptance criteria:** [`fods_redesign_acceptance_criteria.md`](fods_redesign_acceptance_criteria.md)

## Product direction

FODS Research Studio is an editorial research workspace with an inspectable execution engine. The research surface helps a person ask a focused question and read a cited brief. The execution surface makes the actual dependency graph, queue decisions, task-state dictionary, stacks, source work, and event history understandable. The runtime remains authoritative: a visualization is event-derived, or it is clearly described as a teaching model.

The visual language pairs warm paper tones and readable serif headings for research with a deep ink canvas and restrained state colors for FODS Lab. Strong section structure, whitespace, rules, and typography establish hierarchy; cards are reserved for meaningful grouped content. Controls and status labels use direct language. Color is always paired with text, shape, or iconography.

### Design patterns adapted from official references

- **Airflow:** its graph view makes directed task dependencies and run-specific states inspectable, and lets a user select a task to drill into task details. FODS should use a selectable dependency canvas and a run selector, without copying Airflow's operational dashboard or controls. [Airflow UI overview](https://airflow.apache.org/docs/apache-airflow/stable/ui.html)
- **Temporal:** its event history emphasizes scan-friendly rows, related scheduled/started/completed events, event-type and failure filters, and pausing live updates while investigating. FODS should group related lifecycle activity only when its event fields support that relation. [Temporal event history timeline](https://temporal.io/changelog/updated-event-history-timeline-view-is-now-available)
- **Langfuse:** its model distinguishes observations, traces, and optional sessions; nested observations can describe one operation's work, while a trace remains a single operation. FODS should keep an investigation/run separate from a conversational session, because FODS does not currently persist multi-turn conversation sessions. [Langfuse observability data model](https://langfuse.com/docs/observability/data-model)
- **React Flow:** its examples demonstrate custom nodes and edges, graph navigation, selection, layout and accessibility/testing patterns. These are interaction references for a future canvas implementation; no React/React Flow dependency is proposed for the current static prototype. [React Flow examples](https://reactflow.dev/examples)

These are design inferences from the references, adapted to FODS's data and academic purpose.

## Evidence and current-state review

The supplied brief refers to seven owner screenshots, but the attachment directory available in this checkout contains only the pasted brief. I could not inspect those images. The following issues are therefore source-based findings or items to validate against the screenshots, not claims about pixels I have not seen.

| Finding from current source/events | Evidence | Design response |
|---|---|---|
| Draft configuration and selected result share the same Research route; the question field is not rebound to a selected investigation. | `shell.js` reads `#shell-question` only when submitting a new run; answer and events render from `currentRun()`. | Give the composer an explicit **New investigation draft** identity. Show the selected investigation's immutable submitted question, mode, run ID, and result in a separate result region. |
| Replay is created as a new replay run, but the next-run mode select can still say Live. | `replayRun()` sets the selected run to `run_kind: "replay"`; composer mode is independent. | Keep selected-investigation provenance in a persistent run header; label composer settings **Next investigation** and never use them to describe the selected run. |
| The event cursor opens at the latest event, which can be `run_finished`; active queue and task panels are then correctly empty. | `connectEvents()` follows live events to the end; `shell-core.js` derives active tasks at the cursor. | At completion, show a clear empty terminal state plus a one-click **Inspect execution** cursor target (first dispatch / busiest activity). Keep the full-range cursor and terminal state. |
| A final empty queue can be legitimate; a missing queue snapshot is different. | `queue_updated` carries `ready_queue`; absence of a recorded snapshot cannot prove emptiness. | Display `Empty — all tasks dispatched/completed` only when reconstructable. Otherwise display `Queue state not recorded`. |
| Worker IDs are absent. | Runtime events carry task ID, attempt, timestamps; no stable worker identifier. | Show an overlap timeline as **Concurrent execution lanes (inferred)**. Never call lanes Worker 1/2/3. Defer true workers pending instrumentation decision. |
| Current primary views use generic event lists, raw event JSON, task-state rows and stack-history rows. | `index.html` / `shell.js` render these directly. | Replace raw JSON as the default with readable event summaries and structured fields; make raw JSON a collapsed secondary inspector. Draw dictionary pairs and per-task LIFO stacks as their own visual forms. |
| Evidence cards may have no stored excerpt. | Current evidence render uses `evidence.excerpt` when available; context may contain abstract or metadata only. | Render only stored excerpt/text and label its source (`Selected excerpt`, `Abstract`, or `No excerpt recorded`). Never synthesize quote text. |
| The screenshots' reported question/answer mismatch cannot be confirmed from the missing images. | Source separates composer state and selected run state but has no explicit selected-run question heading in the new shell. | Add a one-run identity contract and automated tests that assert the selected run's question, mode, brief, citations, and evidence render together. Treat any screenshot mismatch as an acceptance bug until tested. |

### Selected-run identity contract

Every result view is keyed by one selected `run_id`. The submitted question, actual execution mode (`LIVE`, `SIMULATION`, `REPLAY`), answer, citation validation, saved brief, evidence, trace and FODS Lab projection must be read from that run or its linked source run where the API explicitly records it. A **New investigation draft** has a different visual container and never overwrites the selected run's question/mode. A follow-up is presented as a new linked run and states whether it reuses a saved context or refreshes sources. It is not a chat turn.

## Navigation and terminology

Primary navigation: **Research · Trace · FODS Lab · Library**. Primary action: **New investigation**. Use **Recent investigations**, **Selected investigation**, and **Saved context**. Do not call the experience Chat, conversation, thread, or session unless the backend later stores a durable multi-turn session and run linkage.

Replay is selected from a saved investigation in Library or the investigation header. It is not an execution mode in the new-investigation composer. The selected item shows `REPLAY` and its source run ID; draft settings are separately titled `Next investigation`.

## Shared layout and visual system

### Surfaces

- **Research surface:** light parchment background, ink text, editorial title/question hierarchy, restrained teal for evidence links, a broad reading column, and evidence details in a right drawer. Avoid a dashboard grid of same-weight cards.
- **Execution surface:** dark blue-black canvas, high-contrast labels, thin graph edges, task shapes that communicate type/state, and aligned event/timeline rows. State colors: blue active, teal complete, amber waiting/retry, red rejected/failed, gray not recorded/cancelled. Pair each with state text and accessible contrast.
- **Shared chrome:** compact left rail with the four destinations, current workspace title, recent investigations and a persistent selected-run provenance strip. Technical controls live under a disclosure called **Advanced execution settings**.

### Low-fidelity global frame

```text
┌──────────────────┬─────────────────────────────────────────────────────────────┐
│ FODS Research    │ Selected investigation: RUN-… · SIMULATION · Completed      │
│ Studio           ├─────────────────────────────────────────────────────────────┤
│                  │ Research | Trace | FODS Lab | Library                       │
│ New investigation│                                                     Inspect │
│ Recent           │                                                             │
│ investigations   │             Active surface / selected run                   │
│                  │                                                             │
│ • Graph methods  │                                                             │
│ • RAG review     │                                                             │
│                  │                                                             │
│ Context library  │                                                             │
└──────────────────┴─────────────────────────────────────────────────────────────┘
```

On small screens, the rail becomes a navigation drawer, the inspector becomes an overlay, and the execution timeline scrolls horizontally with its time ruler pinned. Respect reduced-motion preferences; all playback actions remain keyboard accessible.

## Screen specifications

### 1. Research — empty state

**Purpose:** start a research investigation without asking the researcher to understand execution internals first.

```text
┌────────────────────────────────────────────────────────────────────┐
│ Research                                                         │
│ What do you want to investigate?                                   │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Ask a focused research question…                                │ │
│ └────────────────────────────────────────────────────────────────┘ │
│ Topic (optional) [_____________________________________________]   │
│ ○ Real research · searches configured academic sources             │
│ ○ Synthetic demo · deterministic example data                     │
│ [Start investigation]   Advanced execution settings ▸             │
│                                                                    │
│ Try: How does attention aggregate graph neighborhoods?              │
│      What trade-offs appear in retrieval-augmented generation?      │
└────────────────────────────────────────────────────────────────────┘
```

The composer is the main visual focus and accepts a question before an optional topic. Real research and synthetic demo are separate labeled choices; do not mix fixture papers into real source calls. Use concise helper text to describe network/provider requirements. Advanced settings expose planner, scheduler, concurrency, source count, output filename and context reuse for assessment/debugging; defaults remain available without foregrounding knobs. No replay choice is shown here. Suggested questions populate the draft but are not submitted. Validation errors remain next to the relevant field.

**Data mapping:** mode choice → `NewRun.mode`; question/topic → request; context choice → existing context ID/topic only where supported; selected historic investigation is not mutated by composing.

### 2. Research — active investigation

The page preserves the submitted question and the selected run header. A seven-stage progress rail explains the work: **Plan → Retrieve → Merge → Select evidence → Draft → Validate → Brief**. Map a stage to actual event kinds; when stage boundaries are not recorded, present a best-effort event-backed stage and mark it as such, not as a measured duration.

```text
┌────────────────────────────────────────────────────────────────────┐
│ Investigation · SIMULATION · RUN-…                    [Open Trace] │
│ “How do graph attention methods use neighboring nodes?”            │
│ Plan ━ Retrieve ━ Merge ━ Select evidence ━ Draft ━ Validate ━ Brief│
│ 2/3 tasks complete · 1 running · 0 waiting                           │
│ Evidence arriving: [stored paper card] [stored paper card]           │
│                                                                    │
│ New investigation draft remains separate below / behind composer.  │
└────────────────────────────────────────────────────────────────────┘
```

Show source/model attribution only from recorded run metadata/events. Unknown stays `Not recorded`. The progress summary uses task states and actual event counts. Show evidence as it arrives only when events expose it. Failures and waiting work are first-class states. Do not report a model as used because it is configured.

**Data mapping:** question/mode/run ID from the selected run record; status and task transitions from persisted event sequence; source/model attribution from source/model lifecycle events; evidence from `evidence_selected`/context endpoints. Event timing supports durations only when a start and terminal event can be paired reliably.

### 3. Research — completed brief

The brief becomes the dominant reading surface. Use a title from stored topic/question, a short summary only if the answer has an actual summary structure, section headings from the saved brief, inline citation links, and source list. Do not invent summary, findings, excerpt, authors, source identity, or semantic support. If the backend only produces a single answer string, show it as the answer rather than manufacturing structured findings.

```text
┌────────────────────────────────────────────────────────────────────┐
│ SIMULATION · RUN-… · Completed                                      │
│ How do graph attention methods use neighboring nodes?               │
│ Citation IDs verified · semantic support not evaluated              │
│                                                                    │
│ [Stored answer text with linked [P1] citations]                     │
│                                                                    │
│ Sources / evidence     ·     [Open Trace] [Open in FODS Lab]        │
│ P1 · exact stored text, or “No excerpt recorded”                    │
└────────────────────────────────────────────────────────────────────┘
```

Citation click opens an evidence inspector with stored paper metadata, source/URL, abstract and exact excerpt when present. Clearly distinguish `Citation ID valid` from semantic entailment (not evaluated). The brief link appears only when saved and citation validation passed. The follow-up action says: **Start a linked investigation** and explicitly identifies context reuse/refresh behavior supported by the backend.

### 4. Trace

**Purpose:** answer what ran, when, and with what result, without turning the first view into raw JSON.

```text
┌────────────────────────────── Trace · RUN-… · SIMULATION ──────────┐
│ Filter: [All lanes ▾] [All status ▾] [Task ▾] [Search events…]     │
│ time      RUN/PLAN    FODS TASKS      SOURCES   TOOLS/MODELS  OUTPUT│
│ 00.0s     plan ───                                            ·     │
│ 00.1s                 search A ───────────                         │
│                         search B ───────────                        │
│ 00.9s                                           merge ──            │
│ 01.2s                                                     answer ·  │
│ Selected event: readable fields ▾   Raw event JSON ▸                │
└────────────────────────────────────────────────────────────────────┘
```

Lanes: Run/planning, FODS tasks, Sources, Tools, Models, Context/evidence, Answer/output. These are event categories, not inferred parent-child spans. Show grouped/nested spans only where parent/activity IDs or exact task linkage support them. Use start/end bars only for reliable event pairs and point markers for single events. When correlation is missing, label the item `Uncorrelated event`; never draw a relationship from timing proximity alone.

Filters include event type/lane, status (failure/retry/pending/complete), task, provider/model, and text. Pause live updates while inspecting. Selecting an event reveals sequence, exact timestamp, supported duration, task/activity/parent IDs as recorded, provider/model, attempt, recovery reason, and concise payload fields. Raw JSON is collapsible. The timeline and accessible event table are two views over the same persisted sequence.

### 5. FODS Lab — DAG view

Use a full-height dark canvas with zoom-to-fit, pan, reset and legend. Draw fan-out/fan-in as directed connector paths; node shape distinguishes task role (source, merge, select, answer, write), and border/label marks the actual task state. Selecting a node synchronizes the shared event cursor, trace, queue, state dictionary and stack. The task inspector shows exact task ID/tool, prerequisites, dependants, readiness, execution attempts and event references.

```text
┌────────────────────────── FODS Lab · SIMULATION · event 08/42 ─────┐
│ [DAG] [Scheduler] [State & stacks]   Play Pause ◀ Step Step ▶ Reset│
│                                                                    │
│          ┌────────────┐        ┌────────────┐                      │
│          │Source A    │ ───┐   │Source B    │ ──┐                  │
│          └────────────┘    └──▶└────────────┘   ├─▶ Merge          │
│          … (actual plan topology and runtime states)                │
│                                                                    │
│ Selected task inspector · readiness · prerequisites · event refs   │
└────────────────────────────────────────────────────────────────────┘
```

### 6. FODS Lab — scheduler view

Show a clearly separate **Recorded run** and **Concept teaching view**.

- **FIFO:** horizontal deque with FRONT and REAR; every item and movement maps to recorded enqueue/dequeue operations. Empty at terminal state only when terminal/last queue event supports that conclusion. When queue snapshots are absent, show `Queue state not recorded`.
- **Priority queue:** show observed dequeue order and priorities from recorded enqueue/dequeue fields. Draw a binary heap only if the runtime event log contains sufficient insertion/priority/tie-sequence data to reconstruct the actual heap array after each operation. Otherwise show a labeled conceptual heap diagram, separate from an observed order table. It must not be clickable as if it were measured execution.
- **Concurrency:** plot task intervals on unlabeled **Concurrent execution lanes (inferred)** only when task start/terminal timestamps support overlap. State explicitly: runtime does not record worker IDs. Do not show worker numbers or imply fixed worker assignment.
- A FIFO vs priority comparison uses the same plan/input and displays two distinct run IDs with recorded dequeue order. No expected result is hard-coded in the observed view.

```text
┌────────────────────── SCHEDULER · event cursor ────────────────────┐
│ FIFO READY DEQUE     FRONT → [task] [task] [task] → REAR            │
│ Recorded operation: enqueue/dequeue · event sequence                 │
│ Queue result: items present / empty recorded / state not recorded   │
├────────────────────────────────────────────────────────────────────┤
│ PRIORITY QUEUE                                                       │
│ Observed dequeue order      | Conceptual heap (visibly labeled)     │
├────────────────────────────────────────────────────────────────────┤
│ CONCURRENT EXECUTION · INFERRED · WORKER IDS NOT RECORDED           │
│ task A ──────────             task B ──────────   time ruler         │
└────────────────────────────────────────────────────────────────────┘
```

**Data mapping:** queue row order is the latest recorded `ready_queue` snapshot at the shared cursor; enqueue/dequeue operation and task are the selected `queue_updated` event. Inferred concurrency bars use task start/end times only. The heap tree remains conceptual unless reconstructable.

### 7. FODS Lab — state and stacks

The task-state dictionary is a two-column key/value visualization: `task_id → recorded state`. Highlight a key/value row only when an event advances the state projection. Do not show hash buckets, hash values, or collision animation; implementation semantics are a normal Python dictionary.

Stacks appear as separate vertical LIFO columns per task with a visible **TOP** marker. Render only stack values from `stack_push` / `stack_pop` payloads; selecting a task scopes the visible stack. If only pushes or a partial history exist, label `Stack history available from event N` rather than reconstructing an absent base. Recovery/failure appears alongside the exact event and attempt, not as a fabricated stack effect.

```text
┌──────────────── STATE AT EVENT 08/42 ──────────────────────────────┐
│ TASK-STATE DICTIONARY               PER-TASK STACKS                  │
│ key: task ID      value: state     alpha          beta              │
│ search_a          running          ┌ tool:a ┐     (no stack event)  │
│ search_b          queued           ├ task:a ┤                       │
│ merge             blocked          └── TOP ─┘                       │
│                                     [stack event inspector]           │
└────────────────────────────────────────────────────────────────────┘
```

**Data mapping:** map values derive from lifecycle events up to the cursor; stacks derive only from task-specific push/pop payloads. Missing event history remains visibly unknown.

### 8. FODS Lab — shared playback and guided scenarios

One event cursor drives DAG state, queue, inferred concurrency, task-state dictionary, stack, selected trace row and event description. Controls: play, pause, step back/forward, reset, speed, live follow, current event/total. Backward stepping is a projection over prior events; label it **View history** and state that it does not undo execution.

Guided lessons are selectable synthetic scenarios: (1) DAG readiness/fan-out/fan-in, (2) FIFO vs priority, (3) bounded concurrency, (4) task-state changes, (5) stack push/pop, (6) failure/retry/recovery. Every lesson states: what is happening, the concept, the event that changes it, and what to observe. Lesson events are tagged synthetic/teaching; they are not merged into a live run or quality benchmark.

### 9. Library

Library is the durable catalog of **investigations** and **saved contexts**, not conversations. Search/filter investigation title/topic, mode, date, and status. Each investigation row shows its run ID, submitted question, actual mode (including replay), status, created time, available brief/trace, and saved-context link only when recorded. A replay action starts replay from a saved source investigation and clearly retains original run identity; it does not create a fresh retrieval/model run. Context rows show topic, context ID/version, paper count, source freshness if available, and investigations that reference the context. If a relation is not recorded, do not invent it.

```text
┌────────────────────────────────────────────────────────────────────┐
│ Library   [Investigations] [Saved contexts]   Search…   Mode ▾     │
│ SIMULATION · RUN-…   “How do graph attention…”   Completed   Brief ↗│
│ REPLAY · RUN-…        Source run RUN-…            Replayed    Trace ↗│
│ SAVED CONTEXT         Graph methods · 4 papers   Updated …  Inspect │
└────────────────────────────────────────────────────────────────────┘
```

**Data mapping:** investigation entries are records from the history API and associated run/brief/event artifacts. Saved context entries come from the contexts API. Links between investigations and contexts appear only when stored IDs establish that relationship.

## Shared event/data-to-visual mapping

| Visual | Authoritative input | Honest fallback |
|---|---|---|
| Investigation question/mode | Persisted run request/metadata; replay source metadata | `Not recorded` if old run lacks it |
| DAG and edges | Validated `plan_received`/`plan_validated` payload | No graph until accepted plan exists |
| Task state | Task lifecycle/state events through selected cursor | `planned` only when plan exists and no transition recorded; otherwise `Not recorded` |
| FIFO/priority queue | Ordered `queue_updated` snapshots/events | `Queue state not recorded`; never infer queue order from DAG readiness |
| Heap tree | Complete insert/dequeue priority/tie sequence plus known implementation contract | Concept-only label, not observed execution |
| Concurrent lanes | Paired start/terminal task timestamps | `Duration unavailable`; no worker identity claim |
| State map | Task ID and state events | Key/value rows; no hash internals |
| Stack | Per-task push/pop payloads up to cursor | Partial-history label when start of stack history is missing |
| Trace correlation | Recorded activity/task/parent IDs | `Uncorrelated`; no nesting inferred by time |
| Source/model attribution | Recorded lifecycle fields | `Not recorded`; configured model is not actual use |
| Evidence excerpt | Persisted evidence/context excerpt | `No excerpt recorded` |
| Citation | Answer markers and validation event | Valid ID is not semantic entailment |
| Brief success | `brief_saved` and valid citation gate | No success link when absent/invalid |

## Architecture boundaries and future contract questions

### Frontend boundary

Use one selected-investigation store and one cursor. View navigation never starts work. The UI consumes existing history, contexts, run, events/SSE, brief and replay APIs; keep browser code out of scheduling, source selection, readiness, retries, queue ordering, citation policy, and file writes. Static prototype data never calls the backend or network.

### Needed later only if accepted design cannot be supported

1. **Event identity/version:** add backward-compatible `schema_version` and stable `event_id`; retain `seq` and existing JSONL readers.
2. **Run-question/mode metadata:** ensure every history/API response exposes the original submitted question, actual run kind/mode, and replay source run ID. Old artifacts can show `Not recorded`.
3. **Span correlation:** normalize activity IDs, parent/causation IDs, start/end timestamps and attempt IDs for model/tool/source/context lifecycle events where known. Do not manufacture spans in the UI.
4. **Queue state:** existing snapshots are enough when present; if logs lack snapshots, add an optional queue event contract only after compatibility impact review.
5. **Worker identity trade-off:** current lanes can be inferred from overlaps but are not worker assignments. Adding worker IDs would require runtime instrumentation that passes stable bounded slot IDs from the worker pool into task lifecycle events. Cost: event schema/API compatibility, tests, privacy/semantics decisions, and persisted-history adapter work. Benefit: truthful worker occupancy visualization. Recommendation: defer; use explicitly inferred concurrent lanes in the first implementation and reassess only if real slot identity is an acceptance need.
6. **Conversation model:** no conversation/session storage is proposed. If multi-turn chat is later desired, add a durable session entity and run/session linkage first; do not simulate it in the UI.

## Prototype limits

The prototype uses bundled, synthetic educational data and illustrative event sequence numbers. It has no backend connection, live retrieval, model calls, persistent sessions, benchmark labels, or real run trace. Its heap and concurrent-lane panels are explicitly labeled conceptual/inferred. It is a visual review artifact, not proof of frontend integration or retrieval quality.

## Research limitations and review note

The official references were reviewed on 2026-11-01. Seven owner screenshots were referenced but were not present in the accessible attachment directory; screenshot-specific observations in the supplied brief remain unverified. This document uses the reported concerns as test hypotheses and grounds implementation findings in the current repo source. No screenshot was fabricated.
