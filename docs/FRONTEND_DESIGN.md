# FODS Research Studio — Frontend Design Proposal

**Phase 2 deliverable · Gate A.** Decision-oriented design for the redesign, with the evidence
for each decision. Audit evidence and severities live in `docs/audit/AUDIT_FINDINGS.md`
(citations below refer to commit `3081afb`).

**Guiding constraint:** the browser renders recorded events and submits requests. It never
schedules, never calls a provider or model, and never receives a secret
(`webapp.py:136-148` exposes only booleans and model names).

---

## 1. Layout and navigation

One navigation surface (sidebar). The top bar carries context only — no second nav (UI-03).

```
┌───────────────┬─────────────────────────────────────────────────────────────┐
│ FODS Studio   │  AI for scientific discovery · 17ee03228c0b   [running ⏱] ● │
│               ├─────────────────────────────────────────────────────────────┤
│  + New        │   ┌───────────────────────────────────────────────────────┐ │
│               │   │ You · 14:02                                           │ │
│  Research  ●  │   │ How are AI systems used to generate hypotheses?      │ │
│  Lab          │   └───────────────────────────────────────────────────────┘ │
│  Trace        │   ┌───────────────────────────────────────────────────────┐ │
│  Library      │   │ Working…  Searching 5 sources · 12s        [trace]    │ │
│               │   │  ✓ plan validated — 24 tasks, 8 levels               │ │
│  RECENT       │   │  ✓ 20 searches → 30 candidates                       │ │
│  ▸ AI disc…   │   │  ● retrieving evidence (8 nodes, 7 edges)            │ │
│    3m · ⏱     │   └───────────────────────────────────────────────────────┘ │
│  ▸ Graphs     │   ┌───────────────────────────────────────────────────────┐ │
│    1h · part. │   │ Answer        [P1] [P2] [C3] …        partial ⓘ       │ │
│               │   │ ┌───────────────────────────┐ ┌─────────────────────┐ │ │
│               │   │ │ prose …                   │ │ Evidence (12)  ▾    │ │ │
│               │   │ │ Worked for 2m 14s · 9 st. │ │ [P1] … [P12]        │ │ │
│               │   │ └───────────────────────────┘ └─────────────────────┘ │ │
│               │   │ [ Open brief ]  [ Copy ]  [ Evidence ⤢ ]              │ │
│               ├─────────────────────────────────────────────────────────────┤ │
│  ● ready      │  ┌─────────────────────────────────────────────────────────┐│
│               │  │ Ask a research question…                       [ + ] [→]││
│               │  └─────────────────────────────────────────────────────────┘│
│               │   Mode: FODS live · 20 papers · 300 s        [ ■ Stop ]      │
└───────────────┴─────────────────────────────────────────────────────────────┘
       280 px                         flexible, max 880 px content column
```

- **Sidebar** (280 px, collapsible to 64 px): `+ New investigation`, four destinations,
  recent investigations (title · relative time · status dot · short id · replay badge),
  runtime indicator at the bottom. Never scrolls the transcript.
- **Thread**: empty state ("What should we investigate?") centred; otherwise a turn per
  investigation: user message → working lines → answer card → summary.
- **Composer**: textarea (1000 chars, counter), `+` menu, send. Mode chip and Stop sit on the
  line beneath it.
- **Evidence**: a column inside the turn at ≥1280 px; a bottom sheet under 1280 px.
- **Brief**: full-height overlay/drawer, never a new tab.
- **Lab / Trace / Library**: full-width pages that render the *active run*; when there is no
  active run they show the run picker rather than an empty canvas.

Behaviour notes: 1280 px and 1920 px are the target widths; 768 px collapses the sidebar to
icons and stacks evidence under the answer. No horizontal page scroll at any of them.

---

## 2. Tokens

All styling comes from tokens; no ad-hoc margins (§4 of `Project_changes.md`, and the owner's
"margin and padding errors" note).

**Colour (light / dark)** — dark is a full set, not an inversion. Support
`prefers-color-scheme` plus a manual toggle persisted per session.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F7F8F7` | `#101413` | app canvas |
| `--surface` | `#FFFFFF` | `#171C1B` | cards, sidebar |
| `--surface-2` | `#F1F3F2` | `#1E2523` | inputs, table stripes |
| `--ink` | `#14181A` | `#E8EDEB` | primary text |
| `--muted` | `#5C6A6F` | `#9AA5A3` | secondary text |
| `--line` | `#E3E7E6` | `#28302E` | borders, rules |
| `--accent` | `#0F6B5F` | `#4FB3A3` | primary action, live state |
| `--accent-weak` | `#E4F1EE` | `#15322D` | accent fills |
| `--ok` | `#1E7A4B` | `#57C08A` | completed |
| `--warn` | `#A85A00` | `#E4A24C` | partial, retry |
| `--err` | `#B4232F` | `#F07A82` | failed |
| `--blocked` | `#6B5D7A` | `#B9A7CC` | blocked / cancelled |
| `--queued` | `#7A8285` | `#8C9491` | planned / queued |

State colours are the *only* place colour carries meaning; everything else is neutral. This
keeps the semantic palette distinguishable for the common colour-vision deficiencies
(teal/green vs amber vs magenta-ish purple, with icons and labels always present — colour is
never the sole signal).

**Type.** No webfonts. CSP is `default-src 'self'` with no `font-src` (`webapp.py:623-627`),
and the current declared families (`Newsreader`, `Plus Jakarta Sans`, `JetBrains Mono`,
`styles.css:1`) never load because there is no `@font-face` and no network access. Use:
`--font-ui: ui-sans-serif, system-ui, "Segoe UI", …`, `--font-reading: ui-serif, Georgia, …`
for answer prose, `--font-mono: ui-monospace, "Cascadia Mono", Consolas, …` for ids and JSON.
Scale (px/line): 32/40, 24/32, 20/28, 16/24, 14/22, 13/20, 12/16.

**Space.** 4-px scale only: `--sp-1..--sp-10` = 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
Radii 6 / 10 / 14. Elevation: 0 (flat), 1 `0 1px 2px rgba(0,0,0,.05)`, 2
`0 8px 24px rgba(0,0,0,.10)` (popover, overlay).

**Motion.** `--t-fast:120ms`, `--t-base:180ms`, `--t-slow:240ms`; `--ease: cubic-bezier(.2,.8,.2,1)`.
Every transition ≤300 ms; `@media (prefers-reduced-motion: reduce)` sets all durations to
`0.01ms` and disables playback auto-advance.

**Accessibility.** Text ≥4.5:1 against its own surface in both themes; focus ring
`2px solid var(--accent)` with `2px` offset, never removed; the SVG graph always has a
text/table alternative (the state map); status updates use one `aria-live="polite"` region.

---

## 3. Component tree, folders, state model

```
stitch_aesthetic_markdown_reader/
  index.html                  # <div id="root">, module script only (no shell-core.js global)
  src/
    main.jsx                  # mount
    app/App.jsx  app/routes.js
    store/store.jsx  store/reducer.js  store/selectors.js
    api/client.js  api/sse.js  api/types.js
    lib/events.js             # describeEvent / phaseFor / classFor / severityFor
    lib/snapshot.js           # fold(events) + applyEvent(model, event)  (incremental)
    lib/graph.js              # levels -> positions, edge paths, cycle detection
    lib/format.js             # durations, relative time, truncation
    ui/…                      # Button, IconButton, Popover, Chip, Badge, VirtualList,
                              # ScrollArea, EmptyState, Tabs, Tooltip, Toast
    sidebar/  composer/  thread/  evidence/  brief/  trace/  lab/  library/
    styles/tokens.css  styles/base.css  styles/app.css
```

`shell-core.js` ceases to be a global script. Its two useful behaviours (`deriveSnapshot`,
`executionLabel`) move into `lib/snapshot.js` as ES modules; the rest (cursor stepping,
lane naming) is replaced.

**Single store, single `activeRunId`:**

```js
{
  runs: { [runId]: {
    id, sourceRunId, engine, pipeline,          // pipeline: "fods-scheduler" | "rla-phases"
    mode, planner, topic, question,
    status, statusReason, startedAt, endedAt, elapsedMs,
    events: [],                                 // append-only, capped
    stream: "idle"|"connecting"|"live"|"historical"|"error",
  }},
  order: [runId…],                              // recents, newest first
  activeRunId: null,
  ui: { page, composer:{mode,topic,advanced…}, lab:{tab,cursor,playing,speed},
        trace:{filter,classes,selectedSeq}, evidence:{citation}, brief:{open,state} }
}
```

- **One SSE manager** (`api/sse.js`): `subscribe(runId)` opens an `EventSource` keyed on
  `activeRunId`, resumes with `?after=<lastSeq>`, batches messages per animation frame,
  dispatches one `EVENT_BATCH`, closes on terminal event, and reports `stream` state.
- **Status is derived, never stored twice:**
  `status = terminal(lastRunFinished) ?? (stream==="error" ? "interrupted" : "running")`,
  reconciled with `GET /api/runs/<id>` on mount, on selection, and after reconnect. The chip
  shows `activeRunId`; a replay shows `id` plus a secondary `from <sourceRunId>`.
- **Cursors are per view, not per run:** Lab and Trace each hold a cursor; both read
  `applyEvent` output so scrubbing does not recompute the world (A-13).
- **Buffers** are capped (e.g. 5 000 events/run, oldest non-active run evicted first).

---

## 4. FODS Lab

### 4.1 Answer to UI-07: labelled phase graph (option a)

The Lab renders the *recorded structure of whatever ran*, and says which structure it is:

| Pipeline | Lab content |
|---|---|
| `fods-scheduler` | Dependency DAG + queue + workers + state map + stacks (below) |
| `rla-phases` | Horizontal **phase rail** with real counts from `stage_payload` |

Why (a) over (b): the data is already recorded (`research_progress.payload.phase` and
`stage_payload`, `webapp.py:371-374`; 50 progress events in `efee736eb669` covering search →
fetch → score → fulltext → extract → resolve → graph → traverse → answer → done), and it can
teach fan-out honestly (5 sources → 30 scored → 10 retained → 10 extracted → 43 graph nodes
/ 33 concepts → an 8-node subgraph). Option (b) — an explanatory empty state plus "run this in
FODS mode" — is honest but leaves the *default* mode empty (the composer starts on `rla`,
`main.jsx:184`) and teaches nothing, which fails §8.3's intent.

**Anti-lying rules for the phase rail** (each is a test):
1. Banner: `RLA pipeline phases · sequential · not a task DAG`.
2. Edges are drawn only in the order the backend declares
   (`run_started.pipeline_stages`), never inferred in the frontend.
3. No words "scheduler", "queue", "worker", "topological", "parallel" on this screen.
4. `fulltext` is rendered as a dashed "Phase 2 stub" stage — never as a completed step.
5. Stage counts come from `stage_payload`; absent counts render "not recorded", never 0.

### 4.2 Dependency DAG (FODS/demo)

- **Layout from recorded Kahn levels.** `plan_validated.payload.levels` is already
  `list[list[str]]` from `plan.py` (validated by `validate_plan`, emitted at
  `runtime.py:229-238`). Column = level index, row = index within the level. No client-side
  layout heuristic; the topology on screen is the topology the scheduler validated.
  Fallback for logs without `levels`: longest-path depth from recorded `depends_on`, labelled
  "levels computed from recorded dependencies".
- Geometry: node 216×76, gutter 96, row gap 28; deterministic positions so replay is stable.
- **Node**: tool name, short task id, state dot + label, `attempt 2/2` when retried,
  `duration_ms` when completed. Real deep runs have 26 nodes across 8 levels
  (`Q01-deep`); parallel branches visibly share a column.
- **States**: `planned → ready → dispatched → running → completed | failed | blocked |
  cancelled`. `ready` from `task_ready`, `dispatched` from `task_dequeued`, `running` from
  `task_started` (the current code conflates these — `shell-core.js:32-35`).
- **Edges**: bezier, arrow at the child; `edge--done` when the prerequisite completed,
  `edge--hot` for 240 ms when a child becomes ready. A diamond exists in real plans
  (`write` depends on `answer` + `citation_check`) and must render as one.
- **Cycle demo**: when a run records `plan_rejected` with a cycle message, render the
  recorded `plan_received.tasks` with the cycle path highlighted and the line "cycle detected
  by replay analysis of the recorded plan — the runtime rejected it, so no task executed".

### 4.3 Queue and scheduler

- **Ready queue**: a real horizontal FIFO — items enter at the tail, leave at the head, and
  each `queue_updated` re-renders the recorded snapshot (`ready_queue`, `runtime.py:300-308`).
  Priority mode shows `priority` and `sequence` plus a heap-shaped hint
  (`runtime.py:135-139`); FIFO snapshots record only ids (`runtime.py:114-115`), so the view
  says "priority not recorded in FIFO mode" instead of inventing one.
- **Worker pool**: N slots = `run_started.concurrency`; a slot is filled from
  `task_dequeued`/`task_started`. Backend adds `worker_slot` (in-flight count at dispatch);
  until then the caption reads "slot order is display order — the runtime records which tasks
  run concurrently, not which worker id". `workerAssignmentsAvailable` stays honest by
  default (`shell-core.js:74`).
- **State map**: table of task → state, attempts, `ready_reason`
  (`source_task` / `prerequisites_satisfied`) and `remaining_prerequisites`
  (`runtime.py:293-297`). This is the accessible alternative to the SVG.
- **Concurrency meter**: active / N, with a peak line from
  `run_finished.provider_max_in_flight_observed` where relevant.

### 4.4 Task stacks

Per-task `stack` arrays from `stack_push`/`stack_pop` (`runtime.py:453-454, 490-493`),
animated as a vertical stack with a TOP marker; the run-level stack shows
`run → task:<id> → tool:<name>`.

**The `stack` array carried by each event is the only source of truth — never a push/pop count
replayed client-side.** In `17ee03228c0b` (8 tasks) the log holds 8 `stack_push` events and 16
`stack_pop` events, which looks like a mismatch and is not: each task pushes two frames — the
task frame inside `task_started` (`runtime.py:443`, carried in its payload) and the tool frame
inside `stack_push` (`runtime.py:454`) — and `stack_pop` is emitted once per frame on return
(`runtime.py:491-493`), giving exactly 8 × 2 = 16 pops. So 2 pops per completed task is normal,
not evidence of cancellation. The view renders `stacks[task_id]` from the latest recorded event
and additionally accepts an out-of-order pop (unwinding the stack) so a cancelled task cannot
leave a wedged visual.

### 4.5 Playback, LIVE vs REPLAY

- Cursor over events, with play/pause, ±1 step, and speeds 0.5×/1×/2×/4× expressed as
  **events per second, not wall-clock** — the caption says so.
- `LIVE` badge only while `stream === "live"` **and** the cursor is at the head. Scrubbing back
  auto-pauses and flips the badge to `REPLAY`.
- Any loaded historical log is always `REPLAY`, with the standing sentence: "serial render of
  a saved log — this is not live concurrency" (§0.3 of the honesty rules).
- Scrub bar: one tick per event, coloured by class, so a 382-event run is navigable.

### 4.6 Concept captions

One dismissible caption per meaningful transition, generated from the recorded event and
throttled to one per 4 s: "all 5 prerequisites completed → `merge` indegree 0 → enters the
ready queue", "stack push: run → task:merge → tool:merge_and_save_context", "priority 30
dispatched before priority 10 (FIFO tie-break by insertion order)". Dismissal persists per
session. This is the part that makes the Lab educational rather than decorative.

---

## 5. Execution Trace

- **Table**: `#`, `Phase`, `Class`, `One-line summary`, `Status`, `Duration`, waterfall bar.
  Sticky header, fixed 32 px rows, keyboard ↑/↓ and Home/End.
- **Phase** comes from the event, not from `kind`: RLA uses `payload.phase`; FODS derives the
  phase from the task's tool (`search_*`/`acquisition_checkpoint` → acquire, merge → merge,
  `retrieve_evidence` → evidence, `draft_cited_answer` → answer, `validate_citations` →
  validate, `write_cited_brief` → write; plan/queue/task/stack/tool → runtime).
- **Class**: plan, queue, task, tool, stack, source, model, evidence, answer, validation,
  output, runtime — colour-coded by the state palette, label always present.
- **Grouping/filters**: collapsible phase groups; filter chips by class/status; text search;
  "failures only". No Prev/Next stepper (UI-11).
- **Waterfall**: `t0` = first event timestamp; offset = `ts − t0`; width = `duration_ms`
  where recorded (`task_completed.duration_ms`, `runtime.py:722`), else a 2 px tick. Scale
  buttons: fit / 10 s / 1 s. Overlapping bars show real concurrency; serial phases show gaps.
- **Detail pane** (on row select, <100 ms): *Summary · Payload (JSON, collapsed) · Timing
  (start offset, duration, gap) · Related* (same `task_id`, paper id, provider — each a jump
  link).
- **Summary bar**: `75 events · 9 phases · 2 failed · 2m 14s`. Duration is
  `run_finished.elapsed_ms` (`runtime.py:880-884`); when it is `null` (today every RLA run,
  `webapp.py:447`) it reads "duration not recorded" rather than a guess.
- **Virtualised** window of ±10 rows around the viewport; never more than ~60 DOM rows.

### 5.1 In-chat status lines, and where the one-liner comes from

While running, the turn shows the same summaries grouped by phase ("plan validated — 24
tasks, 8 levels", "20 searches → 30 candidates", "retrieving evidence (8 nodes, 7 edges)"),
capped at six lines plus "and N more", in one `aria-live="polite"` region throttled to
500 ms. On the terminal event it collapses to `Worked for 2m 14s · 9 steps`, expandable into
the Trace.

**Source of the one-liner: backend field, with one frontend fallback function.**
`RuntimeEvent` gains optional `summary`, `phase`, `class`, `severity`, `duration_ms`
(`events.py:15-24`). The UI uses `event.summary` when present and otherwise calls
`describeEvent(event)` from `lib/events.js`. Both Trace rows and thread status lines call the
**same** function, so §8.5 ("the trace and the in-chat status lines never disagree") is
structural, not a review promise. Backend-only is impossible (82 existing logs will never have
the fields); frontend-only is worse (it would re-implement provider semantics and cannot
produce tool-call durations).

---

## 6. Backend changes (all additive, all backward compatible)

| # | Change | Fields | Why |
|---|---|---|---|
| 1 | `RuntimeEvent` optional enrichment | `summary: str\|None`, `phase: str\|None`, `class: str\|None`, `severity: "info"\|"ok"\|"warn"\|"error"\|None`, `duration_ms: float\|None` | UI-11, one-liners, waterfall |
| 2 | `run_started` additions | `pipeline: "fods-scheduler"\|"rla-phases"`, `pipeline_stages: [{id,label,order}]` (RLA only) | UI-07, A-03 |
| 3 | Authoritative run info | `GET /api/runs/<id>` → adds `status`, `status_reason`, `started_at`, `ended_at`, `elapsed_ms`, `pipeline`, `unavailable_sources` | UI-08, A-01, A-04 |
| 4 | Status in the stream | SSE envelope adds `status` and `status_reason`, or a `run_status` event on change | UI-08 without polling |
| 5 | Terminal-event guarantee | `run_plan` emits `run_finished` in `finally` (incl. `plan_rejected`) | A-01 |
| 6 | RLA durations + failures | `run_finished.elapsed_ms` real value; `failed_sources` names; `stages: [{id, started_ms, duration_ms}]` | UI-11, A-04 |
| 7 | Concept evidence | `research_answer.evidence` also carries `{citation:"C3", concept:{name, year}}` | UI-09 `[C#]` |
| 8 | Worker slot | `task_started.worker_slot` (in-flight count at dispatch) | Lab worker pool |
| 9 | Brief JSON + download | `GET /api/runs/<id>/brief?format=json` → `{run_id, markdown, citations, sources}`; `?download=1` → `Content-Disposition: attachment` | UI-10 |
| 10 | Cancel for RLA | cooperative check between pipeline items → `run_finished(termination_reason="cancelled")` | A-10 |
| 11 | Validation shape | keep `fields`; add stable `code` strings per error | UI-04, A-12 |
| 12 | Path hygiene | workspace-absolute paths relativised before emit **and** one shared sanitiser at the serve layer (SSE, history, brief, replay). Old logs replay with identical semantics; only path redaction differs | A-11 |
| 13 | Stream fallback + handle lifetime | `/api/runs/<id>/events` streams from disk when no live handle exists; `retry: 3000`; finished handles are evicted | A-02 |
| 14 | Capability discovery | `/api/config.capabilities.{ollama_planner,gemini,rla_live}` plus `limits` (the `NewRun` bounds) and `providers`; the UI disables live with a stated reason and defaults to the deterministic demo when `rla_live` is `false` | A-03, UI-02 |
| 15 | Honest citation flag | `citations_validated = not stripped_citations`; neutral "N selected" badge | A-07 |
| 16 | Brief robustness | try/except around the brief read, 2 MiB cap | A-08 |
| 17 | Tolerant log reads + cached history | `read_events` skips corrupt lines; history index cached by path/mtime/size | A-09 |
| 18 | Request origin guard | Origin and Host checks; loopback allow-list plus an env var for the Vite dev origin | A-11 |

Example of the additive change, verified against a real event:

```jsonc
// before (data/fods/runs/17ee03228c0b.jsonl, seq 4)
{"seq":4,"kind":"plan_validated","message":"plan accepted: 8 tasks, 6 topological levels",
 "payload":{"mode":"simulate","schedule":"fifo","levels":[["search_semantic_scholar", …]],
            "dependency_counts":{…},"tool_calls":0,"tasks":[…]},
 "timestamp":1761…}
// after (same event, new optional keys; old readers unaffected)
{"seq":4,"kind":"plan_validated","message":"…","summary":"plan validated — 8 tasks, 6 levels",
 "phase":"plan","class":"plan","severity":"ok","duration_ms":null,
 "payload":{…},"timestamp":1761…}
```

Backward compatibility: `read_events` returns raw dicts (`events.py:55-64`), every consumer
uses `.get`, and `RuntimeEvent` keeps its five positional fields. Old logs replay because the
reader never requires new keys; `visualize.py` ignores unknown fields.

**Explicitly out of scope:** scheduler algorithms, queue policy, retrieval/relevance logic
(`Project_changes.md` §9).

---

## 7. Test plan and slices

### 7.1 Tests

| Layer | Tool | What |
|---|---|---|
| Backend unit | pytest (existing) | enrichment fields, terminal-event guarantee, status transitions, `/brief?format=json`, Origin guard, path relativisation, RLA cancel |
| Golden fixtures | pytest + node/vitest | replay `efee736eb669` (RLA 55 ev), `17ee03228c0b` (simulate 114), `Q01-deep` (live 381): every event gets a summary; `fold === incremental` |
| Component | vitest + @testing-library/react + jsdom | chip id === activeRunId; New investigation resets and closes the stream; citation scroll; brief overlay + sanitisation; `+` menu keyboard contract; trace row select |
| Browser smoke | Playwright (optional) | simulate run → Lab populated → citation click → brief overlay → New investigation |
| Contract | pytest | `test_fods_webapp.py` unchanged; `test_fods_frontend_shell.py` replaced by behavioural tests; delete the d3-vendor test with the vendor code |

Adds as **devDependencies only**: `vitest` (MIT), `@testing-library/react` (MIT),
`jsdom` (MIT); optionally `@playwright/test` (Apache-2.0). Pin exact versions, note the
licence, and confirm `npm ci` + the Docker build still pass. Production bundle gains nothing.

### 7.2 Slices and definition of done

Checks after **every** slice: `python -m pytest tests/ -q`, `python -m ruff check src/`,
`cd stitch_aesthetic_markdown_reader && npm run build && npm test`, then one commit.

| # | Slice | Fixes | Done when |
|---|---|---|---|
| 1 | Foundation: tokens, theme (light/dark), app shell (sidebar + thread + composer), API client, store with single `activeRunId`, one SSE manager | UI-01, UI-03 | first paint = sidebar + prompt + composer; one nav; one stream; build green |
| 2 | Composer `+` menu: mode, config, advanced with validation, mode chip | UI-02, UI-04, A-06 | no config card on the page; invalid input blocked inline; server `fields` rendered |
| 3 | Backend: enrichment, status/`status_reason`, terminal-event guarantee, brief JSON, path hygiene, Origin guard | UI-08 groundwork, UI-11 support, A-01, A-04, A-08, A-11 | `GET /api/runs/<id>` reports real status; old logs replay with identical semantics (only path redaction differs) |
| 4 | Thread + lifecycle: working lines, collapse to "Worked for…", answer card, chip, New investigation, Stop | UI-05, UI-08, A-10 | chip never stale; New investigation test passes; Stop honest per mode |
| 5 | Answer + evidence: citation chips, two-way highlight, scroll-into-view, `[C#]` | UI-09, A-07 | every `[P#]`/`[C#]` resolves, including the last card |
| 6 | Brief overlay: rendered Markdown, copy/download, sanitised | UI-10 | no new tab; XSS test passes |
| 7 | Trace: waterfall, groups, filters, detail tabs, summary bar, virtualisation | UI-11 | 381-event run: one screen, row detail <100 ms, <60 DOM rows |
| 8 | Lab: DAG, queue, workers, state map, stacks, playback, captions, RLA phase rail | UI-07 | demo run fully populated; RLA labelled and non-empty; no "scheduler" wording for RLA |
| 9 | Cleanup: delete legacy shell + vendor, accessibility pass, empty/error states, docs, screenshots, Docker | A-12, A-13, A-14, A-15 | no dead code; axe-clean; Docker builds; docs state measured counts |

Gate B then verifies on a clean checkout.

---

## 8. Deviations from `Project_changes.md`

1. **UI-07 → option (a) phase graph** (the doc asks the agent to choose). Justified in §4.1.
2. **No Markdown library.** A ~80-line renderer for the fixed subset the brief writer emits,
   instead of `react-markdown` + plugins (three dependencies, CSP irrelevant, injection risk).
   Revisit only if briefs gain arbitrary Markdown.
3. **No state-management library.** `useReducer` + Context instead of Zustand/Redux; the store
   is small and the reducer is trivially testable.
4. **Module test stack added.** `vitest` + Testing Library + jsdom are required to satisfy
   UI-05's "covered by an automated UI test"; they are dev-only and licence-checked.
5. **`shell-core.js` retired.** It becomes `src/lib/*.js`; the `/shell-core.js` and vendor
   routes (`webapp.py:669-686`) are deleted with the dead legacy shell. The existing
   source-grep test is replaced, not deleted, by behavioural tests using the existing
   synthetic fixture (`tests/fixtures/fods_frontend/demo_data.json`).
6. **`run_kind` left alone.** Pipeline identity is a new `pipeline` field rather than a new
   `run_kind` value, to avoid breaking replay labelling.
7. **No accuracy or relevance claims.** The Library and answer footer carry a standing
   "retrieval quality pending human review" note (§0.5).

---

## 9. Decisions needed from the owner

1. **Restore the code first.** The working tree (`main`) has no `src/fods` and no frontend
   source, so nothing can be built, tested, or served. Check out
   `codex/research-frontend-5paper-checkpoint` in this worktree, or should I create a
   worktree for it?
2. **UI-07:** approve option (a) phase graph with a backend-declared stage list? (Option (b)
   explanatory empty state remains the fallback.)
3. **Dev dependencies:** approve `vitest` + `@testing-library/react` + `jsdom` (MIT), and
   optionally Playwright (Apache-2.0) for the browser smoke test?
4. **RLA Stop:** implement cooperative cancellation in the RLA pipeline (touches shared
   pipeline code, not the FODS scheduler), or hide Stop for RLA runs?
5. **Budget default:** show the configured cap (15) verbatim with an explicit "raise for this
   run" override, or keep the current floor of 100 with a warning?
6. **Trace one-liners:** backend emission + frontend fallback (recommended), or frontend
   mapper only?
7. **Dead code:** delete the legacy shell (`src/fods/web/index.html`, `app.js`, `shell.js`,
   `styles.css`, `vendor/d3-*`) and its server routes, moving `shell-core` logic into the React
   package?
8. **Docker:** commit `Dockerfile`, `compose.yaml`, `requirements-docker.lock`,
   `.dockerignore` (currently untracked on `main`) onto the working branch — required for the
   "Docker builds" definition of done.
