# Project_changes.md — FODS Research Studio: Frontend Redesign + Pipeline Audit

> **Status:** first-draft requirements (owner's first thoughts).
> **Agent autonomy:** everything below is a *suggestion*, not a spec. The agent may choose a
> better architecture, layout, colour system, or component structure, **provided it fixes every
> issue in §3, satisfies the acceptance criteria in §8, and justifies the deviation in the design
> proposal (Gate A)**.
> **Screenshots:** `docs/ui-review/` (file names are referenced throughout; see the index in §2).

---

## 0. Read this first (context for the agent)

- **What the project is:** FODS Research Agent. A user enters a topic and question; the backend
  plans bounded academic searches, builds a task DAG, schedules it with queues and bounded workers,
  selects evidence, validates citation IDs, and writes an evidence-backed brief. Its purpose is to
  make Fundamentals-of-Data-Structures concepts (DAG, topological readiness, FIFO/priority queue,
  maps, per-task stacks, event log) **visible in a working agent**. Read `docs/master.md` and
  `README.md` before anything else.
- **Frontend location:** `stitch_aesthetic_markdown_reader/` (React 19, Vite 6, Lucide React).
  It is served by `python -m fods.cli serve` (port 8765) and in dev via `npm run dev` (Vite proxies
  `/api` to 8765).
- **Hard rules that must survive the redesign** (from `docs/master.md`):
  1. The frontend **does not schedule** and **does not call providers or LLMs**. It renders
     backend events and submits requests.
  2. **Honesty over polish.** `partial`, `abstained`, "source failed", and "full-text is a Phase 2
     stub" must be shown truthfully. Never hide a failure to make the UI look cleaner.
  3. **Replay is serial rendering of a saved log**, not evidence of live concurrency. The UI must
     not imply otherwise.
  4. Citation validation is an **ID/provenance check**, not a semantic entailment check. Do not
     label it "verified true".
  5. Retrieval quality is **PENDING HUMAN REVIEW**. Do not add "accuracy" claims.
  6. Two distinct pipelines exist: **FODS** (task scheduler) and **RLA** (phase pipeline, used by
     "Live literature"). The UI must never present RLA phases as if they were FODS scheduler
     output (see UI-07).

---

## 1. Goal of the redesign

Drop the current frontend implementation and rebuild it as a **coding-agent-style workspace**
(think ChatGPT desktop "Work" mode / Codex), not a multi-page research form:

- Left **sidebar** = navigation + history of past investigations ("chats").
- Centre = a **conversation thread** where each investigation is a turn: your question, live
  "working" status, then the answer card.
- **Composer at the bottom** with a **`+` menu** that holds everything currently scattered across
  the right-hand panels (mode, agent configuration, advanced parameters).
- **FODS Lab** (graph / queue / stacks) and **Execution Trace** remain first-class — they are the
  core of the project — but are redesigned to be live, animated, and genuinely explanatory.
- A coherent **colour theme** and layout system, with proper spacing (the current UI has margin and
  padding errors).

Reference layout: `REF-chatgpt-desktop-layout.png` (sidebar with Recents, "New chat", centred
prompt, composer with `+`, model selector, mic/send, and Project / Files / Plugins chips below).

---

## 2. Screenshot index → issue map

| File | What it shows | Issues |
|---|---|---|
| `01-research-home-layout.png` | Current Research page: form + right-hand panels | UI-01 |
| `02-03-agent-config-and-execution-mode.png` | Agent configuration card, Run progress card, Execution mode cards | UI-02 |
| `04-06-duplicate-nav-advanced-params-new-investigation.png` | Top nav duplicating sidebar; advanced params; "New investigation" button | UI-03, UI-04, UI-05 |
| `07-lab-dependency-graph-empty-live-chip.png` | FODS Lab with empty dependency graph; header chip "starting"; "live" label | UI-07, UI-08 |
| `08-trace-page-stale-starting-chip.png` | Execution Trace page (51/51 events) while header chip still says "starting" | UI-08, UI-11 |
| `09-lab-after-run-partial-no-graph.png` | Lab after the run finished: still "No validated task plan was recorded" | UI-07 |
| `10-answer-chip-stuck-partial.png` | Answer view; header chip shows a `partial` badge | UI-08, UI-09 |
| `11-citation-click-no-scroll-chip-id-mismatch.png` | Clicked `[P3]`; card highlighted but not scrolled into view; header chip ID (`b948cacdf295`) differs from the selected recent run (`325edac762e4`) | UI-09, UI-08 |
| `12-open-cited-brief-link.png` | "Open cited research brief" link | UI-10 |
| `13-brief-opens-raw-text-new-tab.png` | Result: new tab at `/api/runs/<id>/brief`, raw monospace Markdown | UI-10 |
| `REF-chatgpt-desktop-layout.png` | Target interaction model | UI-01, UI-02 |
| `REF-devtools-network-waterfall-overview.png` | Chrome Network: time-axis overview + request list | UI-11 |
| `REF-devtools-network-detail-pane.png` | Chrome Network: row selected → Headers/Preview/Response/Timing pane | UI-11 |

> Note the owner's circled numbers on the screenshots do not map 1-to-1 to file numbers; use the
> `UI-xx` IDs below as the source of truth.

---

## 3. Issues and requested changes

Each item: **symptom → owner request → suspected cause (verify in code, do not trust) →
acceptance**. "Suspected cause" is a hypothesis from reading screenshots only; the agent must
confirm against the code in the audit phase.

### UI-01 — Layout is a form page, should be a coding-agent workspace
- **Symptom:** `01-research-home-layout.png` — a large "Frame the inquiry" form with side panels;
  looks like a questionnaire, not an agent.
- **Request:** Chat-style layout. Sidebar holds history of previous investigations; the chat
  composer sits at the bottom; results appear in the thread above it.
- **Suggested structure (agent may improve):**
  - Sidebar (collapsible): `New investigation` · nav (Research, Lab, Trace, Library) ·
    **Recent investigations** list (title, mode, status dot, short ID, relative time) · runtime
    status at the bottom.
  - Main: empty state ("What should we investigate?") → thread of turns.
  - Composer: multi-line input with char counter (limit stays 1000), optional **Topic** field
    (inside the `+` menu or as a small chip), send button, Stop button while running.
- **Acceptance:** First screen shows only sidebar + centred prompt + composer. No right-hand
  config panels. Works at 1280 px and 1920 px widths; usable at ~768 px.

### UI-02 — Agent config / execution mode / run progress clutter the page
- **Symptom:** `02-03-…png` — "Research instruments", "The research sequence", and three big
  mode cards all compete with the form.
- **Request:** Collapse into a **`+` button in the composer** that opens an overlapping popover /
  menu (like ChatGPT's plugins/skills picker). Suggested menu contents:
  1. **Execution mode** (radio): Live literature (RLA) · FODS live research · Deterministic demo.
     Show a one-line description under each. Selected mode appears as a small **chip below the
     composer**.
  2. **Agent configuration** (read-only info rows): structured model, answer model, paper sources
     count. Add "provider reachability is confirmed during an actual request" as helper text.
  3. **Advanced parameters** (see UI-04).
  4. **Topic label** (optional).
- **Run progress** ("SEARCH, FETCH, SCORE, FULLTEXT…") should **not** be a permanent card. Show it
  as live status inside the thread during a run (see UI-11) and as phases in the Lab/Trace.
- **Acceptance:** Zero persistent config panels on the main screen; `+` menu is keyboard
  accessible (open with click or shortcut, Esc closes, focus is trapped and restored).

### UI-03 — Duplicate navigation (top bar and sidebar)
- **Symptom:** `04-06-…png` — Research / Execution Trace / FODS Lab / Library appear **twice**.
- **Request:** Keep **one** navigation (sidebar). Remove the duplicate. Top bar, if any, should
  carry only context (current investigation title, status chip, runtime-ready indicator).
- **Acceptance:** Each destination is reachable from exactly one nav surface.

### UI-04 — "Advanced agent parameters" placement
- **Symptom:** `04-06-…png` — an accordion inside the form with *Papers to keep (20)*, *Provider
  cooldown wait (300 s)*, *Model requests for this run (100)*.
- **Request:** Move into the composer `+` menu as an "Advanced" section (collapsed by default,
  below the main chat controls). Values persist per session, show defaults, and have validation.
- **Audit hook:** Check these defaults and bounds against backend config (`RLA_LLM_DAILY_BUDGET`
  default is 15; free-tier Gemini is documented as ~20 requests/day/model; UI default is 100).
  Mismatches must be reported (see §5, A-06).
- **Acceptance:** Invalid values are blocked inline with a clear message; backend also validates.

### UI-05 — "New investigation" does not start a new investigation
- **Symptom:** Clicking it when an investigation is open does not create a fresh chat; the old
  run's state (answer, chip, trace) lingers.
- **Request:** It must reset the workspace to the empty composer **without deleting history**,
  clear the active run, clear the header chip, abort any open event stream subscription for the
  previous run, and focus the input. If a run is in progress, the run **keeps running in the
  background** and stays visible in the sidebar with a live status; it must not be cancelled
  silently.
- **Suspected cause:** Active-run state is not cleared / there are multiple sources of truth for
  "current run" (see UI-08).
- **Acceptance:** From any page and any run state, one click gives an empty composer and no stale
  chip. Covered by an automated UI test.

### UI-06 — (merged into UI-03/UI-05; kept for traceability with the owner's numbering)

### UI-07 — FODS Lab shows nothing after execution
- **Symptom:** `07-…png`, `09-…png` — "No validated task plan was recorded", "0 recorded tasks · 0
  declared dependencies", empty dotted canvas, even though 29–75 events exist. Queue & Scheduler
  and Task Stacks tabs likewise provide no useful visual.
- **Likely cause (verify):** The run was **Live literature (RLA)**. Per `docs/master.md` §7 that
  path uses the RLA phase orchestrator, **not** the FODS scheduler, so no FODS plan/queue/stack
  events exist. The Lab is therefore correctly empty for that run type but gives the user no
  explanation, which reads as a bug.
- **Request:** Make the Lab always meaningful and honest:
  1. **FODS live research / Deterministic demo runs:** full, animated visualisation of the real
     scheduler events (below).
  2. **Live literature (RLA) runs:** either (a) show a clearly labelled **"RLA pipeline phases"**
     graph (search → fetch → score → fulltext(stub) → extract → resolve → graph → traverse →
     answer, with provider fan-out and per-paper extraction fan-out), **or** (b) show an
     explanatory empty state with a button "Run the same question in FODS mode". The agent should
     propose which, with reasons, at Gate A. Never label RLA phases as the FODS scheduler.
  3. If the backend must emit extra events for (a), define them in the design proposal.
- **Lab visual requirements** (this is the core of the project — design it carefully):
  - **Dependency graph:** layered DAG layout computed from the plan (Kahn levels = topological
    layers, left→right). Nodes show tool name, state, attempt count, duration. Edges show
    dependency; edge highlights when the prerequisite completes. Parallel branches visibly sit
    in the same layer. Node states: queued · ready · in-flight · completed · failed · blocked ·
    skipped. A cycle-rejection demo state should be visualisable.
  - **Queue & Scheduler:** show the **ready queue** as an actual FIFO queue (items enter at the
    tail, leave at the head) or priority heap (with priority values and tie-breaking by insertion
    order), a **worker pool** with N bounded slots showing which task occupies each, a
    **task-state map** (task ID → state/retries), and a **concurrency meter**. Toggle FIFO vs
    priority when the run recorded both or in demo mode.
  - **Task stacks:** per-task call stack (run → task → tool) pushing/popping with time.
  - **Playback:** scrubber + play/pause/step/speed; "live" mode follows the head of the stream and
    auto-pauses when the user scrubs back; clear **LIVE vs REPLAY** badge (replay is serial; say
    so).
  - **Concept callouts:** small, dismissible captions tying what's on screen to the data
    structure ("indegree reached 0 → task enters ready queue"). This is what makes it
    educational.
  - Animations: smooth, purposeful, ≤300 ms per transition, respects `prefers-reduced-motion`.
- **Acceptance:** A deterministic-demo run produces a populated, animated graph, queue/worker
  view and stacks with no console errors; a Live-literature run produces either the labelled
  phase graph or the explanatory empty state; no screen is ever blank without an explanation.

### UI-08 — Stale / inconsistent run status chip
- **Symptom:** (a) `08-…png` — chip says **starting** while the trace has all 51 events. (b)
  `10-…png`, `11-…png` — the **partial** chip stays visible after switching/starting work. (c)
  `11-…png` — chip shows `b948cacdf295` while the highlighted recent run is `325edac762e4`.
- **Suspected cause (verify):** the header chip reads from a different state source than the
  sidebar/selected run; it is set on `run_started` and not updated from the terminal event; it is
  not cleared on New investigation or run switch.
- **Request:** **One store, one `activeRunId`.** Status is *derived* from the run record / event
  stream (`starting → running → completed | partial | failed | cancelled | abstained`), reconciled
  with the server on load and on SSE reconnect. Chip is hidden when there is no active run.
  `partial` should be explainable: hover/click shows *why* (e.g. "Semantic Scholar failed; DBLP
  bot-check").
- **Acceptance:** Chip ID always equals the selected run's ID; status matches `GET /api/runs/<id>`
  within one refresh; test covers start → complete, start → partial, switch run, new
  investigation, page reload mid-run.

### UI-09 — Clicking a citation does not scroll / reliably highlight the evidence card
- **Symptom:** `11-…png`, `12-…png` — click `[P3]` / `[P9]`: card tints but the evidence list
  (its own scroll container) does not bring it into view.
- **Request:** Clicking a citation chip **scrolls the matching card into view inside the evidence
  panel** (smooth, `block: "nearest"` or centre), applies a brief highlight pulse, and keeps it
  selected until another is chosen. Hovering a card should highlight its citations in the answer
  (two-way link). Concept citations `[C#]` should resolve too (show concept detail or the
  supporting paper). Keyboard-operable. If the panel is collapsed on narrow screens, open it
  first.
- **Acceptance:** Works for every `[P#]`/`[C#]` in the answer, including the last card in a long
  list; no layout shift of the answer text.

### UI-10 — "Open cited research brief" opens raw text in a new tab
- **Symptom:** `12-…png` → `13-…png` — navigates to `/api/runs/<id>/brief`, a monospace plain-text
  dump.
- **Request:** Open the brief **inside the app** as an overlay/drawer ("background" panel) that
  does not navigate away. Render Markdown properly (headings, paragraphs, lists), render `[P#]`
  /`[C#]` as the same interactive citation chips, show the "Subgraph used" list as a structured
  source list. Provide **Copy**, **Download .md**, and **Close** (Esc). The raw endpoint stays for
  downloads (consider `Content-Disposition` for `?download=1`).
- **Security note:** the brief is written under a caller-named, workspace-scoped path. Make sure
  the read endpoint cannot be used for path traversal and that rendered Markdown is sanitised
  (no raw HTML injection).
- **Acceptance:** No new tab opens; keyboard and screen-reader accessible; handles very long
  briefs and a missing brief file with a clear message.

### UI-11 — Execution Trace redesign + "working" messages in chat
- **Symptom:** `08-…png` — flat list of `research_progress` rows plus a JSON payload pane; hard to
  scan; a Prev/Next stepper at the top that the owner finds unnecessary; very noisy.
- **Request (trace page):**
  - Redesign as a **timeline / waterfall** inspired by Chrome DevTools Network
    (`REF-devtools-network-waterfall-overview.png`, `REF-devtools-network-detail-pane.png`):
    top **overview strip** (time axis with phase bars), main **table** with columns such as
    `#`, `Phase`, `Class/Kind`, `One-line summary`, `Status`, `Start`, `Duration`, and a
    **waterfall bar** per row. Sticky header, resizable columns optional.
  - Group by phase with collapsible groups (search, fetch, score, extract, …). Colour by
    class/kind. Filter chips by kind/status; text search; "failures only".
  - **Click a row → detail pane** with tabs: *Summary · Payload (JSON) · Timing · Related events*
    (e.g. same task/paper ID). Keep raw JSON available but secondary.
  - **Bottom summary bar** like the Network tab: `75 events · 9 phases · 2 failed · finished in
    2m 14s`.
  - Virtualise long lists (runs can have hundreds of events).
  - Remove the "Previous event / Next event" top stepper (keyboard ↑/↓ replaces it).
- **Request (one-liners — likely needs backend):** The raw log is not pleasant to read. Each
  event should carry a short human `summary` (≤ ~90 chars), e.g. `Extracted 3 concepts from
  W3015636663 (10/20)`, `Semantic Scholar failed: 429 rate-limited`, plus `phase`, `class`,
  `duration_ms`, and `severity`. If the backend cannot add these cleanly, derive them in a single
  tested frontend mapper — the agent decides and justifies. Existing event schema fields
  (`seq`, `kind`, `message`, `payload`, `timestamp`) must remain backward compatible so old runs
  still replay.
- **Request (chat "working" messages):** While a run is in progress, show **status lines in the
  thread** (like ChatGPT/Claude "Thinking… / Searching sources… / Reading 12 abstracts…"),
  derived from the same events. Collapse to a "Worked for 2m 14s · 9 steps" summary when the
  answer arrives; expanding it shows the timeline. Tone must be accurate (no fake "thinking").
- **Acceptance:** A 75-event run can be understood from one screen without opening JSON; selecting
  a row shows its detail in <100 ms; the trace and the in-chat status lines never disagree.

---

## 4. Design guidance (suggestions only)

- **Theme:** the current UI is light with a serif display font. Agent may propose a new coherent
  system. Suggested direction: calm neutral surfaces, **one** accent colour, semantic colours for
  states (completed/in-flight/queued/failed/blocked), light **and** dark themes via CSS variables
  with `prefers-color-scheme` support and a manual toggle.
- **Tokens first:** define colour, spacing (4-px scale), radius, elevation, type scale, and motion
  tokens in one place; no ad-hoc margins. The owner noticed padding/margin errors — consistency
  of spacing is an explicit acceptance item.
- **Accessibility:** WCAG AA contrast, visible focus rings, ARIA for the `+` popover, tabs,
  graph (provide a text/table alternative to the SVG graph), live regions for status updates,
  reduced-motion support.
- **Tech choices:** keep React 19 + Vite 6 + Lucide unless there is a clear reason. Prefer
  dependency-light solutions (SVG + CSS transitions for the graph, a small virtual-list helper).
  Any new dependency needs a one-line justification, a pinned version, and a licence check; the
  Docker build and offline `npm ci` must still work.
- **State:** a single typed store (reducer/Context or a tiny store) holding runs, activeRunId,
  event buffers per run, UI state. SSE connection managed in one place with reconnect and
  last-event-ID resume.
- **Structure:** feature folders (`composer/`, `thread/`, `evidence/`, `lab/`, `trace/`,
  `sidebar/`, `brief/`), shared `ui/` primitives, an API client module with types matching the
  backend schemas.

---

## 5. Pipeline audit (required, do this BEFORE changing code)

The owner wants a **general audit of the whole working pipeline** — not only the UI — to find
where it can fail, where loose ends exist, and what to fix. The agent must **investigate, report,
and wait for approval** before fixing (see `AGENT_PROMPT.md`, Gate A).

For every finding report: **ID · symptom · evidence (file:line or command output) · root cause ·
severity (blocker / major / minor) · proposed fix · approach & alternatives · risk · test to
prove it**. Do not report anything as a bug without evidence; label unverified ideas as
"hypothesis".

Audit checklist (non-exhaustive; add what you find):

| ID | Area | What to check |
|---|---|---|
| A-01 | Run lifecycle / status | Is there a single state machine? What status is stored if the server dies mid-run (zombie `starting`/`running`)? Are terminal states always written? Is `partial` vs `failed` vs `abstained` well defined? |
| A-02 | Event stream | SSE reconnect, duplicate/out-of-order events, `seq` gaps, back-pressure, closed streams after completion, memory growth for long runs |
| A-03 | Mode semantics | Exactly which pipeline runs for each mode; which events each mode emits; does anything differ between simulate and live that the UI hides? |
| A-04 | Provider failures | Retry/backoff/cool-down behaviour (Semantic Scholar failure, DBLP bot-check HTML treated as JSON?, 429s), whether failures are surfaced in `partial` reasons, and timeouts per attempt |
| A-05 | Retrieval/selection | Weak matches in selected sets (see 20-paper QA note in `docs/master.md`); dedup correctness; candidate caps; whether "Papers to keep" actually bounds output |
| A-06 | Config/limits | UI defaults (20 papers / 300 s / 100 requests) vs backend defaults and documented quotas (`RLA_LLM_DAILY_BUDGET`, free-tier ~20/day); server-side validation of every request field |
| A-07 | Citation integrity | Citation IDs in the draft vs evidence; `[C#]` concept IDs vs `[P#]` paper IDs handling; what happens when IDs are stripped; wording of the UI claim ("0 unsupported IDs stripped") |
| A-08 | Brief endpoint/writer | Path scoping, traversal, overwrite policy ("use a new output path each run"), missing-file behaviour, content-type, size limits |
| A-09 | Persistence | Run/context/graph artifacts under `data/fods/`; schema-v1 vs schema-v2 graph snapshot mismatch noted in README; concurrent writes; corrupted JSONL line handling on replay |
| A-10 | Concurrency | Two runs at once, double-submit, New-investigation during a run, cancel/stop support (no Stop button is visible today) |
| A-11 | Security | Loopback binding, CORS, secret handling (keys must never reach the browser), Markdown/HTML sanitisation, request-size limits, error messages leaking paths |
| A-12 | Error UX | Every failure path gives the user a readable message and a next step; no blank screens; no silent catches |
| A-13 | Performance | Trace/graph rendering with hundreds of events, bundle size, unnecessary re-renders, SSE handler cost |
| A-14 | Tests & docs drift | README says 668 tests passed, `docs/master.md` says 808 (+1 skipped) and 797 historically — reconcile; check every command in the docs actually works on a fresh clone; check doc links |
| A-15 | Packaging | Docker image builds and serves the new frontend; `requirements-docker.lock` and `package-lock.json` consistent; `.env.example` complete; no secrets or large artifacts committed |

---

## 6. Backend changes that are probably needed (agent to confirm/decide)

1. **Event enrichment** — add `summary`, `phase`, `class`, `severity`, `duration_ms` (additive,
   backward compatible; old logs still replay).
2. **Run status endpoint/field** that is authoritative and includes `status_reason` (why
   partial/failed) and `ended_at`.
3. **Brief as JSON** — e.g. `GET /api/runs/<id>/brief?format=json` returning
   `{markdown, citations, sources}`; raw/download variant retained.
4. **Plan/phase events for RLA runs** if the Lab phase-graph option is chosen (UI-07).
5. **Cancel** endpoint/command if feasible (supports the Stop button and A-10).
6. **Request validation** with clear 4xx messages for the advanced parameters.
7. Keep CLI behaviour, existing tests, and the `--mode simulate --planner fixture` path intact.

---

## 7. Submission readiness (the project must end "ready to submit")

- All tests pass (`python -m pytest tests/ -q`), `ruff check src/` clean, `npm run build` clean,
  new frontend unit tests pass, and a browser smoke test (Playwright or equivalent, if available)
  covers: simulate run, citation click, brief overlay, New investigation, Lab populated, Trace
  selection.
- Old frontend code **removed**, not left alongside; no dead routes, unused assets, or commented-out
  blocks.
- `README.md`, `docs/master.md`, demo script/checklist/artifact inventory updated to match the new
  UI (screenshots refreshed; test counts reconciled; faculty framing and limitations preserved —
  do **not** upgrade claims about research quality).
- Docker image builds and runs the new UI; fresh-clone setup instructions verified step by step.
- A final **`docs/SUBMISSION_REPORT.md`**: what changed, audit findings and their status
  (fixed / deferred / accepted risk), test evidence, known limitations, how to run the demo in
  under 5 minutes.
- Git hygiene: one commit per slice with a clear message; working tree clean at the end.

---

## 8. Global acceptance criteria

1. Every UI-xx item in §3 is fixed and demonstrated with a screenshot in the submission report.
2. No duplicate navigation; single source of truth for the active run; chip never stale.
3. The Lab is never silently empty and visibly teaches the data structures on FODS/demo runs.
4. Brief opens in-app, rendered, with working citation chips.
5. Trace is scannable (timeline + one-liners + detail pane) and consistent with in-chat status.
6. Spacing, colour and type come from tokens; light and dark themes both pass contrast checks.
7. Audit findings are all either fixed (with a test), or explicitly listed as deferred with
   rationale and owner approval.
8. The honesty rules in §0 still hold everywhere in the UI copy.

---

## 9. Out of scope (unless approved)

- Changing the FODS scheduler algorithms or the research relevance logic.
- Adding new academic providers or new models.
- Full-text/PDF processing.
- Anything that makes the frontend call providers or schedule work.
