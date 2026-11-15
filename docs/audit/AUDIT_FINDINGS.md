# FODS Research Studio — Pipeline & Frontend Audit

**Phase 1 deliverable.** Read-only audit of the FODS backend (`src/fods/`) and the React
frontend (`stitch_aesthetic_markdown_reader/`), covering every `UI-xx` in
`Project_changes.md` §3 and every audit area `A-xx` in §5.

**Date:** 2026-11-15
**Status:** awaiting Gate A approval. No code has been modified.

---

## 0. Scope, method, and a blocking environment fact

### 0.1 Where the code actually is

The working tree is on `main` (`9152a05`) and **does not contain the subject code**:

| Check | Command | Result |
|---|---|---|
| FODS sources tracked | `git ls-files src/fods` | `0` files |
| FODS sources in `HEAD` | `git ls-tree -r --name-only HEAD -- src/fods` | empty |
| Frontend sources | `Get-ChildItem stitch_aesthetic_markdown_reader` | only `node_modules` — no `package.json`, `src/`, or `index.html` |
| Import | `.venv\Scripts\python.exe -m fods.cli --help` | `No module named fods.cli` |

The implementation lives on branch `codex/research-frontend-5paper-checkpoint`
(`3081afb`, 2026-11-15): 29 files under `src/fods/`, 21 files under
`stitch_aesthetic_markdown_reader/`. It was exported read-only with
`git archive` and audited at
`%TEMP%\opencode\fods-audit\tree`.

**Every `file:line` citation below refers to commit `3081afb`**, not to files in the
current working tree. The `.venv` is an editable install pointing at
`D:\Research_AI_Agent-fods\src` (`.venv/Lib/site-packages/_editable_impl_rla.pth`), so
the package cannot be imported until those sources are restored.

### 0.2 Baseline runs: NOT EXECUTED (blocked, not skipped)

`Project_changes.md` asks for reproduced baselines. They could not be produced:

| Command | Result |
|---|---|
| `python -m pytest tests/ -q` | cannot collect — `fods` is not importable in this tree |
| `python -m ruff check src/` | no `src/fods` to lint; `src/` contains only `rla` |
| `cd stitch_aesthetic_markdown_reader && npm run build` | no `package.json` |
| `python -m fods.cli serve` | `No module named fods.cli` |

So **no pass/fail count in this document was measured by me.** Static test counts are
reported as static counts (§A-14). The three documented numbers (668 / 742 / 808) remain
unreconciled until the suite runs once on the restored tree.

What I *did* run, and its output: git inspections, `grep`/`Select-String` counts over
source, and a parse of the **82 recorded run logs** in `data/fods/runs/`. Those logs are
first-party evidence of real runtime behaviour and are used heavily below.

### 0.3 Conventions

- **Confirmed** = I read the code path and/or observed the recorded data.
- **Hypothesis** = inferred, not verified; flagged inline.
- Severity: **blocker** = fails a §8 acceptance criterion or the core purpose;
  **major** = wrong, misleading, or costly behaviour with a fix; **minor** = debt,
  robustness, or polish.

---

## 1. Summary

| Severity | Count | IDs |
|---|---|---|
| Blocker | 2 | UI-07, UI-08 |
| Major | 18 | UI-01, UI-02, UI-04, UI-05, UI-09, UI-10, UI-11, A-01, A-02, A-03, A-04, A-06, A-07, A-10, A-11, A-12, A-14, A-15 |
| Minor | 5 | UI-03, A-05, A-08, A-09, A-13 |
| Merged / no independent defect | 1 | UI-06 |
| **Total IDs audited** | **26** | 11 `UI-xx` + 15 `A-xx` |

Two findings are the same defect seen from two sides and should be fixed once:
**UI-08** (stale chip) and **A-01** (no run state machine) both reduce to
"`RunHandle.status` is written but never read, and there is no terminal-state guarantee".

---

## 2. UI findings

### UI-01 — Layout is a form page, not a coding-agent workspace

**Symptom.** `01-research-home-layout.png`: a large "Frame the inquiry" form with two
permanent right-hand cards; reads as a questionnaire. The transcript, the composer, and
run history are not the primary surfaces.

**Evidence.**
- `ResearchPage` renders a two-column `.research-grid` containing `<section className="composer">`
  and `<aside className="side-column">` (`main.jsx:242-290`).
- The aside holds `provider-card` (`main.jsx:280`) and `progress-card`
  (`main.jsx:281-288`) unconditionally — they are not gated by run state.
- The composer is a `<form>` at the top of the document (`main.jsx:245`), not a bottom
  composer inside a thread.
- Navigation is page-switching on a `page` string (`main.jsx:385`, `393-396`), so there is
  no per-investigation transcript at all; `SideRail` lists at most 12 runs
  (`main.jsx:152`) and has no "New investigation" entry.
- The results block only appears *below* the form (`main.jsx:292-303`), so the answer and
  the question that produced it are separated by a 400 px form.

**Root cause.** Confirmed: the page is a document/form layout, not a conversation. There is
no "turn" concept in the data model or the component tree.

**Severity.** Major — it is the owner's primary goal, and UI-02/UI-05 cannot be fixed
cleanly without this shell.

**Proposed fix.** Rebuild the shell as three regions: fixed **sidebar** (nav +
recents + runtime indicator), scrollable **transcript** (one card per investigation turn),
and a **bottom composer** with a `+` menu. Config surfaces move into the `+` menu
(UI-02). Results (answer, evidence, status lines) render inside the turn.

**Approach & alternatives.**
- *Chosen:* restructure the existing React app into feature folders, keeping
  `useWorkspace`'s event plumbing (`main.jsx:44-131`) as the basis of the new store.
  Lowest risk to the backend contract; the event vocabulary is already correct.
- *Rejected:* restyling the current page — cannot satisfy "first screen shows only sidebar
  + centred prompt + composer" (§UI-01 acceptance) because the two-column grid is the layout.
- *Rejected:* a fresh app in a new directory — the existing 401-line file must be split
  anyway (§4 requires feature folders); creating a second app would duplicate the API client.

**Risk.** `tests/test_fods_frontend_shell.py:84-101` asserts literal strings inside
`index.html` and `src/main.jsx` (in order: `<div id="root"></div>`,
`src="/shell-core.js"`, `src="/src/main.jsx"`, the strings "Execution Trace", "FODS Lab",
"Library", four event kinds, `reuse_context`, `graphLayout(tasks)`, `deriveSnapshot`, and
`prefers-reduced-motion` in `styles.css`). A rewrite breaks this test. It must be replaced
with behavioural tests in the same slice, not deleted silently.

**Proof.**
- Component test: first paint contains one `navigation` landmark, one composer, and zero
  config cards.
- Playwright/viewport check at 768/1280/1920 px: no horizontal scroll; the composer is
  reachable without scrolling.
- `test_fods_webapp.py` unchanged (proves the API contract survived).

---

### UI-02 — Agent configuration, mode cards, and run progress clutter the page

**Symptom.** `02-03-agent-config-and-execution-mode.png`: "Research instruments",
"The research sequence", and three large mode cards compete with the question field.

**Evidence.**
- Three mode cards are always rendered inside the form (`main.jsx:251-255`).
- "Research instruments" is a permanent card (`main.jsx:280`); "Run progress" is another
  (`main.jsx:281-287`), showing a nine-row phase list computed from events
  (`main.jsx:282-287`).
- Only the advanced grid is collapsible (`showSettings`, `main.jsx:190`, `257-274`).

**Root cause.** Confirmed: these surfaces were built as page content, not as composer
attachments.

**Severity.** Major.

**Proposed fix.** Move all three into a composer `+` popover with four sections: Execution
mode (radio + one-line description each), Agent configuration (read-only rows), Advanced
(collapsed), Topic label. Show the selected mode as a chip under the composer. Replace the
permanent progress card with in-thread status lines (UI-11).

**Approach & alternatives.**
- *Chosen:* one popover, keyboard-trapped, with the selected mode summarised as a chip.
  This matches the reference layout (`REF-chatgpt-desktop-layout.png`).
- *Rejected:* keeping mode cards visible under the composer — still competes with the input
  and does not scale to the 3 modes + future ones.
- *Rejected:* a separate settings route — adds navigation, which UI-03 is trying to reduce.

**Risk.** The popover must preserve the context-reuse validation that currently lives in
`submit()` (`main.jsx:216-218`) and the topic-to-context matching (`main.jsx:204`). Losing
it silently would produce 400s instead of inline guidance.

**Proof.**
- Component test: `+` opens on click and on `Mod+.`; Esc closes; focus returns to the
  trigger; Tab cycles inside only while open (focus trap); `aria-expanded`/`aria-controls`
  present.
- Snapshot of the research page: no element with `data-testid="config-card"`.

---

### UI-03 — Duplicate navigation (top bar and sidebar)

**Symptom.** `04-06-...png`: Research / Execution Trace / FODS Lab / Library appear twice.

**Evidence.**
- `Header` renders `<nav className="primary-nav">` mapping `NAV` (`main.jsx:139-141`).
- `SideRail` maps the same `NAV` constant (`main.jsx:150`) from the same array
  (`main.jsx:12-17`).
- Both are mounted simultaneously by `App` (`main.jsx:391`).

**Root cause.** Confirmed: the header was extended with navigation when the sidebar already
owned it; the `NAV` array is shared, which makes the duplication look intentional.

**Severity.** Minor (visual/IA), but it is an explicit §8.2 acceptance item.

**Proposed fix.** Delete `primary-nav`. The header carries only: investigation title, status
chip (with a "replayed from" suffix when applicable), and the runtime indicator.

**Approach & alternatives.**
- *Chosen:* single sidebar nav.
- *Rejected:* single top nav — the sidebar is where recents live, and the reference layout
  keeps nav there.

**Risk.** Low. `NAV` is also the source of page keys; keep it exported from one module so
the sidebar and route table cannot drift.

**Proof.** Test: exactly one `navigation` landmark; each destination label appears exactly
once in the accessibility tree.

---

### UI-04 — "Advanced agent parameters" placement, defaults, and validation

**Symptom.** `04-06-...png`: an accordion stuck inside the form, with *Papers to keep (20)*,
*Provider cooldown wait (300 s)*, *Model requests for this run (100)*, and no visible
validation messaging.

**Evidence.**
- Accordion: `main.jsx:257-274`; state at `main.jsx:190`.
- Defaults hardcoded in state: `paperLimit=20`, `waitSeconds=300`, `budget=100`
  (`main.jsx:181-183`).
- Values are overwritten from `/api/config` on load, with a forced floor of 100 for the
  budget: `setBudget(Math.max(100, config.llm_request_budget || 100))` (`main.jsx:210`).
- Submission sends `Number(...)` unchecked (`main.jsx:224-225`); HTML `min`/`max` attributes
  (`main.jsx:259-261`) do not prevent submission and produce no inline message.
- Server-side validation exists and is strict (`webapp.py:55-57`, `59-80`), but the UI never
  renders the returned `fields` array (`main.jsx:28` reads only `body.error`).

**Root cause.** Confirmed: placement is form-local; validation is delegated to native
constraint UI; and the budget default is deliberately overridden upward (see A-06).

**Severity.** Major.

**Proposed fix.** Move to `+` → Advanced (collapsed), persist per session, show the
default and its source, validate inline before submit, and render server `fields[].msg`
next to the offending input.

**Approach & alternatives.**
- *Chosen:* local validator mirroring the pydantic bounds, plus server errors mapped back by
  field name. Keeps one authority (the server) while giving instant feedback.
- *Rejected:* relying on `min`/`max` — inconsistent across browsers and silent on submit.
- *Rejected:* a form library — unnecessary dependency for 5 fields.

**Risk.** Duplicated bounds drift from `NewRun`. Mitigation: derive the UI bounds from
`/api/config` (add `limits: {...}` there — see §Backend changes in the design doc) and keep
one constant table with a test that compares it to the pydantic model.

**Proof.** Test that a 400 response containing `fields` renders one message per field; test
that entering `0` for the budget blocks submit with a visible message and does not POST;
test that omitting the field sends the backend default unchanged.

---

### UI-05 — "New investigation" does not start a new investigation

**Symptom.** Clicking the button while an investigation is open leaves the old answer, chip,
and trace on screen.

**Evidence.**
- The button's entire handler is `onClick={() => setPage("research")}`
  (`main.jsx:143`). It does not clear `run` (`main.jsx:49`), `events` (`main.jsx:50`),
  `active` (`main.jsx:51`), or `error`, does not close the `EventSource`
  (`main.jsx:53`, `85-86`), and does not focus the textarea (`main.jsx:247`).
- `start()` refuses while a run is active: `if (active) throw ...`
  (`main.jsx:111`); the same guard exists for replay (`main.jsx:122`).
- The submit button is disabled while active (`main.jsx:276`), so the only affordance
  available during a run is the one that does nothing.
- `App` force-navigates to Research on any new run (`main.jsx:389`), which masks the
  problem for new runs but not for the reset case.

**Root cause.** Confirmed: "New investigation" is a navigation action, not a state
transition. There is no notion of "clear the workspace".

**Severity.** Major — §8.2 and the UI-05 acceptance ("covered by an automated UI test").

**Proposed fix.** A store action `newInvestigation()` that: closes the active stream, clears
`activeRunId` + the visible event buffer, keeps history, leaves any running server-side run
untouched (it is an independent thread, `webapp.py:227-233`), and focuses the composer.
Reopening a running run from the sidebar re-subscribes to it.

**Approach & alternatives.**
- *Chosen:* per-run event buffers in the store, with only one "viewed" run. This is required
  anyway to keep a background run visible with a live status, which the owner explicitly
  asks for (§UI-05 request).
- *Rejected:* actually cancelling the run on New investigation — contradicts the requirement
  that it "keeps running in the background".

**Risk.** Buffering events for runs that are no longer viewed grows memory; cap each buffer
and drop the oldest non-active buffer first (UI-13 budget). Also: if the user starts a new
run while another is live, two SSE connections exist — the server tolerates this
(`webapp.py:227`), but see A-10 for the cross-run cost.

**Proof.** UI test: with a mocked `EventSource`, start a run, click "New investigation";
assert (a) the composer is empty and focused, (b) no chip is rendered, (c) the mock stream
was closed, (d) the sidebar still lists the running run, (e) re-selecting it restores events.

---

### UI-06 — merged

No independent defect. The owner folded this item into UI-03 and UI-05; this audit agrees
(duplicate nav = UI-03, non-functional reset = UI-05). No action.

---

### UI-07 — The FODS Lab is empty after execution

**Symptom.** `07-lab-dependency-graph-empty-live-chip.png` and
`09-lab-after-run-partial-no-graph.png`: "No validated task plan was recorded",
"0 recorded tasks · 0 declared dependencies", dotted canvas. Queue and Stacks tabs are
equally empty.

**Evidence — which pipeline runs, and which events each emits.**

| UI mode | Request built at | `engine` / `mode` / `planner` | Executor | Events emitted |
|---|---|---|---|---|
| Live literature | `main.jsx:223-225` | `rla` / `live` / n/a | `RunManager._execute_research_pipeline` (`webapp.py:326-485`) | `run_started` (`350`), `research_progress` (`368`), `research_papers` (`381`), `research_answer` (`410`), `brief_saved` (`423`), `run_finished` (`439`); errors add `run_failed` (`470`) |
| FODS live | `main.jsx:229-233` | `fods` / `live` / `auto→ollama` (`webapp.py:197-198`) | `fods.cli._execute` → `run_plan` | full scheduler vocabulary: `plan_received`, `plan_validated`, `task_ready`, `queue_updated`, `task_dequeued`, `task_started`, `stack_push/pop`, `task_completed`, … (`runtime.py`) |
| Deterministic demo | `main.jsx:226-228` | `fods` / `simulate` / `fixture` | same as above, fixture planner | same as above |

`start()` rejects `engine=rla` with non-live mode (`webapp.py:160-161`), so those three are
the only reachable combinations.

- The Lab builds its model solely from `plan_validated` / `plan_received`
  (`shell-core.js:15-18`). An RLA run emits neither, so `tasks` is `[]` and `GraphView`
  renders its empty state (`main.jsx:346`, counter at `main.jsx:370`).
- **Recorded proof.** Of the 82 logs in `data/fods/runs/`, 3 are RLA runs
  (`67b25b50f5ab`, `c2383fb60ace`, `efee736eb669`) with `plan_validated` count **0** and
  `research_progress` counts **31 / 53 / 50**. The other 79 are FODS runs: 73 record exactly
  **1** `plan_validated` and **0** `research_progress`; the remaining 6 record neither
  (3 `plan_rejected`, 2 `failed` during query planning, 1 with no terminal event — see A-01).
- **The default mode is the broken one.** `engine` initialises to `"rla"` (`main.jsx:184`),
  so a first-time user gets the empty Lab by default. It is not an edge case.
- Nothing in the stream tells the UI which vocabulary is in play: `RunHandle` is created with
  `request.mode` (`webapp.py:220`), so `run_kind` is `"live"` for both RLA and FODS-live; the
  SSE envelope carries only `run_kind` and `source_run_id` (`webapp.py:770-774`). The Lab
  badge therefore says "live" for an RLA run (`main.jsx:368`).

**Root cause.** Confirmed: two distinct pipelines with disjoint event vocabularies; the Lab
understands only the scheduler vocabulary; and there is no field identifying the pipeline, so
the UI cannot even explain the emptiness.

**Severity.** **Blocker** — it is the core of the project and §8.3 forbids a silently empty Lab.

**Recommendation: option (a), the labelled phase graph.** Reasons:
1. **The data exists.** `research_progress.payload` already carries `phase`
   (`webapp.py:371`) and `phase_kind`. A real run yields exactly
   search → fetch → score → fulltext → extract → resolve → graph → traverse → answer → done
   (`efee736eb669`, 50 progress events).
2. **It can teach, which (b) cannot.** `stage_payload` carries real counts: 5 sources
   (`fetch`), 30 papers scored (`score`), 10 reused extractions (`extract`), 43 nodes /
   33 concepts / 36 edges (`graph`), an 8-node / 7-edge subgraph (`traverse`). That is a
   genuine fan-out story, and §8.3 asks the Lab to teach the structures rather than apologise.
3. **One mental model.** "The Lab shows the recorded structure of whatever ran" holds for
   both pipelines; (b) leaves the *default* mode with an empty screen plus a button.
4. **Honesty is enforceable if the backend declares the stage list.** Edges must be declared
   by the backend (`run_started.payload.pipeline_stages`), never invented in the frontend,
   and the panel must state: *sequential pipeline stages — not a task DAG; no queue, no
   scheduler, no concurrency*.

Option (b) remains the fallback if the owner prefers the smallest change; it is honest but
teaches nothing and still reads as "empty" for the default mode.

**Proposed fix.**
1. Backend: `run_started` gains `pipeline: "rla-phases"` and an ordered `pipeline_stages`
   list (id, label, order); `run_finished` for RLA gains a real `elapsed_ms` and per-stage
   durations (see A-03/A-11).
2. Frontend: a `PhaseGraph` component selected by `pipeline`, sharing the Lab's playback and
   caption machinery with the DAG but using distinct node shapes and a "sequential" edge
   style.
3. Both Lab views: an explicit mode banner naming the pipeline, and a "what this is / what
   this is not" caption.

**Risk.** A phase graph invites the reading "these run in parallel". Mitigations: single
row, left-to-right, numbered stages, per-stage duration bar, and the fixed disclaimer text;
no animated fan-out of parallel edges, only a width change for counts.

**Proof.**
- Unit test on a phase-graph builder fed the recorded `efee736eb669` log: 10 nodes, 9 ordered
  edges, each node's count badge matching `stage_payload`.
- Regression test on `17ee03228c0b` (simulate): `pipeline === "fods-scheduler"`, 8 tasks,
  6 recorded levels, no phase rail.
- Browser test: the Lab is never rendered with both an empty canvas and no explanatory
  banner; text audit asserts the word "scheduler" never appears for an RLA run.

---

### UI-08 — Stale / inconsistent run status chip

**Symptom.** (a) `08-trace-page-stale-starting-chip.png`: chip says **starting** while the
trace shows 51/51 events. (b) `10-...png`, `11-...png`: a **partial** chip persists after
moving on. (c) `11-...png`: chip shows `b948cacdf295` while the highlighted recent run is
`325edac762e4`.

**Evidence — every place that holds "current run" or "status":**

| Source of truth | Where | What it holds | Failure mode |
|---|---|---|---|
| `RunHandle.status` | `webapp.py:91` (init `"starting"`), written only by `finish()` `webapp.py:105-110` | final status | never becomes `"running"` — nothing assigns it |
| `RunHandle.events` | `webapp.py:92`, appended in `publish()` `webapp.py:99-103` | live buffer | unbounded; lost on restart |
| SSE envelope | `webapp.py:770-774` | `run_kind`, `source_run_id`, `event` | carries **no** status |
| `<id>.jsonl` | `webapp.py:219`; read by `history()` `webapp.py:500` | full log | status only if a `run_finished` event exists |
| `_status_from_finish` | `webapp.py:597-607` | derived status | returns `"unknown"` when the finish event is absent |
| Browser `run` / `events` | `main.jsx:49-50` | the viewed run | replaced only by `watch()` (`main.jsx:78-108`) |
| `run.source_run_id` | set by `replay` (`main.jsx:126`, `webapp.py:546`) | the replayed log's id | a second identity, shown by `SideRail` (`main.jsx:152`) |

- **(a)** The chip renders `run.status || ...` (`main.jsx:138`), and `run.status` is only
  assigned when `run_finished` arrives (`main.jsx:92-95`). Before that it is the value the
  server returned from `_handle_info`, i.e. `"starting"` from `webapp.py:91`. The server
  never updates it during the run, and the client never polls `GET /api/runs/<id>`. Hence the
  chip reads "starting" for the entire run while the trace fills up — exactly screenshot 08.
- **(b)** `run` is global (`App` renders `Header` outside the page switch,
  `main.jsx:391`), and nothing clears it on navigation or on "New investigation"
  (`main.jsx:143`). The `partial` label itself is legitimate
  (`termination_reason === "completed_with_partial_sources"`, `main.jsx:94`); the defect is
  that it outlives the run it describes.
- **(c)** `Header` prints `run.run_id` (`main.jsx:138`); `SideRail` highlights
  `run?.source_run_id === item.run_id || run?.run_id === item.run_id`
  (`main.jsx:152`). Clicking a recent run calls `/api/replay`, which mints a **new**
  `run_id` (`webapp.py:545-546`) and returns it (`webapp.py:801`), while the sidebar
  highlights the **source** id. Two ids, both correct, neither labelled as "replay of".

**Root cause.** Confirmed. Five sources of truth, no reconciliation, and a status field that
is write-only on the server.

**Severity.** **Blocker** — §8.2 requires the chip to never be stale; it is stale by
construction, and the acceptance test in UI-08 cannot pass.

**Proposed fix.** One store, one `activeRunId`, status **derived**:
- Server: set `handle.status = "running"` on the first published event; add `status`,
  `status_reason`, `started_at`, `ended_at`, `elapsed_ms`, `pipeline`, `engine` to
  `_handle_info` (`webapp.py:829-841`) and to a new `run_status` SSE event (or to the
  envelope) so the chip updates without polling.
- Client: `status = f(runRecord, lastEvent, streamState)` with the enum
  `starting | running | completed | partial | failed | cancelled | interrupted`.
  Chip hidden when `activeRunId` is null; for a replay, chip shows the replay id with a
  secondary "from `325edac762e4`" label.
- `partial`/`failed` get a `status_reason` popover (A-04).

**Approach & alternatives.**
- *Chosen:* derive from (record + events), reconciled on load via `GET /api/runs/<id>`.
  Survives reload and reconnect without persisting anything new.
- *Rejected:* storing a status file per run — adds a second persistence format that can
  disagree with the log.
- *Rejected:* optimistic client-side "running" from `run_started` alone — it would claim
  progress a stalled run is not making.

**Risk.** Adding `running` changes what `_handle_info` returns and could affect
`tests/test_fods_webapp.py`. That file asserts on `RunHandle`/`RunManager` behaviour; the
change is additive (a string value that was previously always `"starting"`), so tests that
assert `"starting"` *during* a run would be asserting the bug and must be updated
deliberately.

**Proof.**
- Backend: `GET /api/runs/<id>` returns `starting` before the first event, `running` after,
  and the terminal value after; `test_fods_webapp.py` gains three assertions.
- Frontend: chip id === `activeRunId` in every state; a replay test asserts chip = replay id
  and the "from …" label = source id; a reload-mid-run test rehydrates from `/api/runs/<id>`.

---

### UI-09 — Clicking a citation does not scroll to or reliably highlight the evidence

**Symptom.** `11-...png`, `12-...png`: clicking `[P3]`/`[P9]` tints a card, but the evidence
list (its own scroll container) does not move; ids in the chips do not resolve.

**Evidence.**
- `inspectCitation` only sets state:
  ``const inspectCitation = (citation) => setSelectedEvidence(evidence.find(...) || null)``
  (`main.jsx:237`). There is **no** `scrollIntoView` call anywhere: `grep -c scrollIntoView`
  over `main.jsx` and `styles.css` = 0.
- The evidence list is truncated: `(evidence.length ? evidence : papers).slice(0, 10)`
  (`main.jsx:300`). Any citation above `[P10]` cannot be rendered, let alone scrolled to.
- `[C#]` chips are parsed by `CiteText` (`main.jsx:171-174`) and passed to the same handler,
  but RLA evidence only includes paper nodes: `if node.type == str(NodeType.PAPER)`
  (`webapp.py:406-409`). Real data confirms concept citations exist in answers: run
  `efee736eb669` has `traverse.stage_payload.nodes` with labels `C1`–`C6`, and its answer
  text cites `[C3]`. So `[C#]` always resolves to `null` and highlights nothing.
- `PaperCard` has no hover/focus hook (`main.jsx:161-168`), so the promised two-way link
  (hover a card → highlight its citations) does not exist.
- Cards are `article` elements with an `onClick` (`main.jsx:162`) — not keyboard operable.

**Root cause.** Confirmed: state-only selection, a hard truncation, paper-only evidence, and
no reverse mapping.

**Severity.** Major.

**Proposed fix.** Per-card `ref` + `scrollIntoView({block:"nearest"})` guarded by
`prefers-reduced-motion`; `scroll-margin-block` on cards to avoid clipping; remove
`.slice(0,10)` (virtualise the list instead, A-13); back each card with a stable
`data-citation` attribute so hover can highlight matching chips; make cards buttons; render
concept evidence from the recorded subgraph.

**Approach & alternatives.**
- *Chosen:* resolve `[C#]` from `traverse.stage_payload.nodes` (already in the event stream)
  and additionally include concept nodes in `research_answer.evidence` (backend, additive) so
  both pipelines expose the same shape.
- *Rejected:* client-only DOM lookup by text — fragile and breaks with virtualisation.

**Risk.** Smooth scrolling inside a nested scroll container can scroll the page instead;
mitigation is `block:"nearest"` plus a tested `overflow` boundary. Removing `.slice(0,10)` on
a 20-paper run means 20 cards — fine; on a long brief it must be virtualised (A-13).

**Proof.** jsdom test with 14 evidence items: click `[P14]` → the 14th card receives
`scrollIntoView`; `[C3]` selects a concept card; `Enter` on a focused card selects it;
hovering card `[P3]` marks the `[P3]` chip; answer text height unchanged before/after
(no layout shift).

---

### UI-10 — "Open cited research brief" opens raw Markdown in a new tab

**Symptom.** `12-...png` → `13-...png`: a new browser tab at
`/api/runs/<id>/brief` showing monospace plain text.

**Evidence.**
- The link is an anchor with `target="_blank"`:
  `<a className="brief-link" href={/api/runs/${run.source_run_id || run.run_id}/brief} target="_blank">`
  (`main.jsx:297`).
- The endpoint returns the file as `text/markdown; charset=utf-8` with no
  `Content-Disposition` (`webapp.py:704-713`), so the browser displays it inline as text.
- Path safety is already implemented correctly: the writer restricts the name to a simple
  `.md` filename (`webapp.py:32`, `151-157`), refuses paths outside the workspace
  (`webapp.py:213-214`), refuses overwrite with 409 (`webapp.py:215-216`); the reader resolves
  and re-checks containment (`webapp.py:591-593`).
- One unhandled crash path: `brief()` calls `read_events(path)` without a guard
  (`webapp.py:584-587`); a corrupt JSONL line raises `ValueError` out of `do_GET`, which has
  no handler (`webapp.py:650-726`), so the client gets a dropped connection instead of a JSON
  error.

**Root cause.** Confirmed: the brief is treated as a download URL, not as content.

**Severity.** Major.

**Proposed fix.** An in-app overlay/drawer rendering the Markdown (headings, paragraphs,
lists, tables in the writer's subset), with `[P#]`/`[C#]` mapped to the same citation chips,
a structured "Subgraph used" source list, Copy, Download .md, Close (Esc). Keep the raw
endpoint for downloads via `?download=1` → `Content-Disposition: attachment`.
Backend: add `?format=json` → `{run_id, markdown, citations, sources}`; wrap the read in
try/except → 500 JSON; cap response size.

**Approach & alternatives.**
- *Chosen:* a small renderer for the exact subset `render_markdown` produces
  (`rla/pipeline/answer.py`), escaping all text and building React nodes. No HTML string is
  ever injected, so no sanitiser is needed.
- *Rejected:* `react-markdown` + `remark-gfm` + `rehype-sanitize` — three new dependencies for
  a fixed, machine-generated format, plus bundle weight and a supply-chain surface.
- *Rejected:* iframe/`<object>` of the raw endpoint — CSP `default-src 'self'` plus
  `object-src 'none'` (`webapp.py:623-627`) would block it, and it still looks like a text dump.

**Risk.** A hand-rolled renderer must handle unexpected content (a paper title containing
`#`, a stray `*`). Mitigation: escape first, then apply a whitelist of block patterns; test
with adversarial input including `<img src=x onerror=alert(1)>`, `<script>`, unbalanced
backticks.

**Proof.**
- Test: the overlay opens without `window.open`; Esc closes and returns focus; focus is
  trapped while open; `aria-modal`/`role="dialog"` present.
- Security test: a brief containing raw HTML renders the tags as literal text; the DOM
  contains no `script`/`img` node created from file content.
- `?download=1` response carries `Content-Disposition: attachment; filename="<run_id>.md"`.
- Missing brief: 404 → overlay shows "No saved brief for this run" with a Close action.

---

### UI-11 — Execution Trace is a flat dump; no in-chat working status

**Symptom.** `08-...png`: flat rows of `research_progress`, a raw JSON pane, and a
Prev/Next stepper.

**Evidence.**
- The row's "phase" cell reads `event.phase || event.kind` (`main.jsx:317`) and the filter
  concatenates `event.phase` (`main.jsx:313`), but `phase` is not a top-level event field —
  it lives at `payload.phase` (`webapp.py:371`). For RLA runs every row therefore renders
  as "research_progress"; run `efee736eb669` has 50 such rows, all identical in that column.
- Stepper: `main.jsx:316` ("Previous event" / slider / "Next event").
- Detail pane is `<pre>{JSON.stringify(selected, null, 2)}</pre>` (`main.jsx:318`) — no
  summary, timing, or related events.
- No summary bar, no grouping, no virtualisation; `events.slice(0, cursor).filter(...)` runs
  on every keystroke (`main.jsx:313`).
- **Duration is not always available.** FODS `run_finished` carries `elapsed_ms`
  (`runtime.py:880-884`) and `task_completed` carries `duration_ms` (`runtime.py:722`), but
  the RLA path emits `elapsed_ms=None` (`webapp.py:447`), so "finished in 2m 14s" (§UI-11)
  is currently impossible for RLA runs. Per-event duration is also absent from
  `research_progress`, which only has `event_timestamp` (`webapp.py:374`).
- The event schema has no `summary`, `phase`, `class`, or `severity`:
  `RuntimeEvent(seq, kind, message, payload, timestamp)` (`events.py:15-24`).
- In-chat working lines do not exist; progress is a permanent card (`main.jsx:281-287`).

**Root cause.** Confirmed, two parts: (i) the trace UI assumes fields the schema does not
have; (ii) the schema genuinely lacks the derived fields, and the RLA path does not record
durations.

**Severity.** Major.

**Proposed fix (decision).** **Backend enrichment plus one frontend mapper**, not one or the
other:
- Backend adds optional `summary`, `phase`, `class`, `severity`, `duration_ms` to
  `RuntimeEvent` (all default `None`) and populates them at the emit sites. Old logs stay
  readable because `read_events` returns raw dicts and every consumer uses `.get`.
- The RLA path emits real durations (stage start/end) and `elapsed_ms`.
- One tested frontend function `describeEvent(event)` fills any missing field from
  `kind`/`payload`, so all 82 existing logs still produce one-liners.
- The **same** function feeds both the Trace rows and the in-chat status lines, which makes
  §8.5 ("the trace and the in-chat status lines never disagree") true by construction rather
  than by review.

Why not frontend-only: the wording needs domain knowledge ("Semantic Scholar failed: 429",
"Extracted 3 concepts from W3015636663") that already exists server-side (tool messages,
`duration_ms`, provider names); duplicating it in the client guarantees drift. Why not
backend-only: 82 existing logs will never have the new fields, and the UI must still show
them.

Plus the UI work: waterfall table (`#`, phase, class, summary, status, duration, bar),
sticky header, collapsible phase groups, filter chips (kind/class/severity) + text + "failures
only", click → detail tabs (Summary / Payload / Timing / Related), bottom summary bar,
virtualised rows, keyboard ↑/↓, stepper removed, and in-thread status lines that collapse to
"Worked for 2m 14s · 9 steps".

**Approach & alternatives.**
- *Chosen:* enrichment + mapper as described.
- *Rejected:* a pure frontend mapper — cannot produce `duration_ms` for tool calls and
  re-implements provider semantics.
- *Rejected:* a new event type per human-readable sentence — inflates the log and makes
  replay heavier.

**Risk.** Touching `RuntimeEvent` affects `events.py`, `visualize.py`, `_print_event`
(`cli.py:418`), and `test_fods_tracing.py`/`test_fods_visualize.py`. All new fields must be
default-`None` and serialised as `null`; `safe_value` must tolerate `None` (it is applied to
the whole payload, `events.py:44`). The visualisation HTML must ignore unknown fields.

**Proof.**
- Golden-file tests: replay `efee736eb669` (RLA, 55 events), `17ee03228c0b` (simulate, 114),
  `Q01-deep` (live, 381) through `describeEvent` and assert 100 % of events yield a non-empty
  summary ≤ 90 chars.
- Python: unit tests for each new field at its emit site; a test that a stored old-format
  log replays unchanged (byte-identical event dicts).
- Browser: selecting a row renders its detail in < 100 ms on the 381-event log; the number
  of DOM rows stays < 60; the in-chat lines equal the trace's first N summaries (same
  function, asserted by comparing outputs).

---

## 3. Pipeline / backend findings (A-xx)

### A-01 — No run state machine; terminal states are not guaranteed

**Symptom.** After a restart or a crash, a run's status is unknowable; the API says 404, the
history says "unknown"; the documented state `abstained` does not exist in the code.

**Evidence.**
- Statuses actually produced: `"starting"` (`webapp.py:91`);
  `"completed" | "partial" | "failed" | "cancelled"` via `finish()` (`webapp.py:105-110`,
  assigned at `283-308`, `453-456`, `467`, `485`); `"replayed"` (`webapp.py:555`).
- `"running"` is never assigned anywhere. `"abstained"` appears nowhere in `src/fods/`
  (`grep -c abstain` = 0), although `UI-08`/§0 name it.
- **Terminal event not guaranteed.** `run_plan` emits `plan_rejected` and then re-raises
  (`runtime.py:226-227`) without emitting `run_finished`. Only the webapp wrapper synthesises
  a finish (`webapp.py:295-307`); the CLI path does not.
- **Recorded zombies.** `data/fods/runs/8c5a5ba36606.jsonl` contains exactly two events
  (`plan_received`, `plan_rejected`) and no `run_finished`; three further files
  (`3086210e157c`, `d298bdfcb8e2`, `4d7926f0d25a`) also end at `plan_rejected`.
- `history()` maps a missing finish to `"unknown"` (`webapp.py:597-600`), and drops the run
  entirely if any line is corrupt (`webapp.py:499-502`).
- Status is never persisted: `GET /api/runs/<id>` returns 404 after a restart because only
  `self.runs` (memory) is consulted (`webapp.py:695-700`, `818-820`).

**Root cause.** Confirmed: the run state is an in-memory dataclass plus an event stream, with
no invariant that a terminal event is written.

**Severity.** Major (it is the root of UI-08).

**Proposed fix.**
1. `run_plan` emits `run_finished` in a `finally` block, including
   `termination_reason="plan_rejected"`.
2. `RunHandle` transitions `starting → running → terminal` with `status_reason`,
   `started_at`, `ended_at`.
3. `history()` reports `"interrupted"` with `status_reason="no terminal event recorded"`
   instead of `"unknown"`.
4. Either emit `abstained` where the answer stage abstains, or remove it from the documented
   enum (decision for the owner).

**Approach & alternatives.**
- *Chosen:* events remain the source of truth for finished runs; the in-memory record is the
  authority only while a run is live. No new file format, so `data/` and replay are untouched.
- *Rejected:* appending a `status` record to the JSONL — a second terminal concept and a
  format change that every reader would have to special-case.
- *Rejected:* a `run.status.json` sidecar — can disagree with the log; needs cleanup.

**Risk.** `test_fods_runtime.py` (19 tests) asserts event sequences and may break when a
rejected plan gains a `run_finished`. That is a deliberate contract improvement; the test
must be updated with the reason written down. Emitting in `finally` touches the scheduler
file but **not** the scheduling algorithm (no queue/ordering change).

**Proof.** Tests: rejected plan → `plan_rejected` + `run_finished(termination_reason=
"plan_rejected")`; truncated log → `history()` returns `interrupted`; live run →
`GET /api/runs/<id>` goes `starting → running → completed`.

---

### A-02 — Event stream: no history replay after restart, no eviction, silent failure

**Symptom.** Reload or reconnect after a server restart loses the run permanently, with no
message. Memory grows with every run.

**Evidence.**
- SSE is implemented on a `ThreadingHTTPServer` (`webapp.py:613`, `826`) with
  `Last-Event-ID` support (`webapp.py:745`), a 1 s keep-alive comment (`webapp.py:761-762`),
  and a clean exit on finish (`webapp.py:779-780`).
- `seq` is contiguous per run: verified on `Q01-deep` — 381 events, min 1, max 381, 381
  unique values.
- `_events` requires a live handle: `handle = run_manager.get(run_id)` → 404 if absent
  (`webapp.py:741-743`). After a restart the JSONL still exists but the stream 404s.
- `self.runs` is never evicted (`webapp.py:124`, `222`, `548`); each finished run keeps its
  full event list (up to 382 events) for the process lifetime.
- The client does not handle stream failure: `stream.onerror` only flips `connected` when
  `readyState === CLOSED` (`main.jsx:105-107`), and `refreshHistory().catch(() => {})`
  swallows errors (`main.jsx:101-102`). A 404 on reconnect therefore produces a permanently
  silent UI.
- No `retry:` field is sent, so the browser uses its default (~3 s).

**Root cause.** Confirmed: three separate gaps — durability of the stream source, lifecycle
of the in-memory buffer, and user-visible stream errors.

**Severity.** Major.

**Proposed fix.** (a) When no handle exists but the log does, stream from disk (honour
`Last-Event-ID`), and mark the connection `historical`; (b) evict finished handles after a
TTL / keep a bounded ring; (c) send `retry: 3000`; (d) surface stream state in the UI
(connecting / live / historical / failed + Retry).

**Approach & alternatives.**
- *Chosen:* file backfill only when `handle is None`, and only for ids matching
  `RUN_ID` inside `runs_dir` (reusing the containment check at `webapp.py:542`).
- *Rejected:* replaying through a synthetic `RunHandle` — creates a fake `run_id` and
  reintroduces the UI-08 identity problem.

**Risk.** A file being appended while it is read can yield a partial last line;
`read_events` raises on a bad line (`events.py:62-63`), so backfill must be tolerant
(see A-09). Also, serving historical streams must not be confused with live concurrency —
the UI must label it (`docs/master.md` honesty rule 3).

**Proof.** Tests: reconnect with `Last-Event-ID: 200` on a finished run replays 201…381;
with the handle removed, the same request still streams 1…381 from disk; a truncated last
line does not abort the stream.

---

### A-03 — Mode semantics: three modes, two vocabularies, differences the UI hides

**Symptom.** The same button set produces structurally different runs, with nothing in the
stream or the UI saying which.

**Evidence.** See the UI-07 table. Additional hidden differences:
- `RunHandle` is constructed with `request.mode` (`webapp.py:220`), so `run_kind` is
  `"live"` for both RLA and FODS-live; the `Literal` type is
  `["live", "simulate", "replay"]` (`webapp.py:86`). Nothing in the SSE envelope identifies
  the pipeline (`webapp.py:770-774`).
- RLA runs reuse cached extraction and graph state: the real `done` payload of
  `efee736eb669` reports `extraction: {reused: 10, extracted: 0}` and
  `cache: {hits: 75, misses: 10}`. The UI presents the run as a fresh investigation.
- FODS live requires an Ollama structured planner and refuses otherwise
  (`webapp.py:192-196`), but the UI enables the mode regardless; the user only learns on
  submit.
- Simulate runs still call `_execute` with the same code path as live, so the event
  vocabulary is identical — the only differences are `mode` and fixtures
  (`webapp.py:248-274`).

**Root cause.** Confirmed.

**Severity.** Major.

**Proposed fix.** Add `pipeline: "fods-scheduler" | "rla-phases"` to `run_started` and
`_handle_info`; keep `run_kind` unchanged for backward compatibility. UI shows a pipeline
badge and, for RLA, "reused 10 cached extractions" when `reused > 0`. Disable FODS-live with
an explanation when `/api/config` reports a non-Ollama planner.

**Approach & alternatives.**
- *Chosen:* a new `pipeline` field. Changing `run_kind` would break `executionLabel`
  (`shell-core.js:87-92`) and the LIVE/REPLAY badge.
- *Rejected:* inferring the pipeline from the first event kind — works only after the fact and
  fails for empty or rejected runs.

**Risk.** `/api/config` currently exposes `gemini_opted_in` and model names but not whether
Ollama is usable; add `capabilities: {ollama_planner: bool}` (additive) rather than making the
UI infer from a model string.

**Proof.** Parametrised test asserting the exact event-kind set per mode; a UI test that the
mode banner differs and that FODS-live is disabled with a reason when the planner is not
Ollama.

---

### A-04 — Provider failures are recorded but never surfaced

**Symptom.** A run says `partial` or `failed` with no reason. The owner must open the JSONL.

**Evidence.**
- FODS records rich failure data on finish: `unavailable_sources`, `successful_source_count`,
  `research_stop_reason`, `http_attempts_by_provider`,
  `provider_max_in_flight_observed`, `http_attempt_budget*` (`runtime.py:868-884`), and maps
  eight distinct `termination_reason` values (`runtime.py:822-845`).
- RLA records only the aggregate: `complete and source_failures` →
  `"completed_with_partial_sources"` (`webapp.py:431-435`); the actual
  `failed_sources` mapping is not included in `run_finished`.
- The UI displays only the status word (`main.jsx:138`, `main.jsx:244`) and never reads
  `unavailable_sources`.
- Recorded distribution across the 82 logs in `data/fods/runs/`:
  **33** `completed`, **16** `completed_with_partial_sources` (the ten `Q01..Q10-quick` runs
  plus six others), **15** `task_failed_or_blocked`, **10** `completed_at_research_target`,
  **3** `plan_rejected`, **2** `failed`, **2** `pipeline_incomplete`, **1** with no terminal
  event. So **39 of 82 runs (48 %) end in something other than a clean `completed` or
  `completed_at_research_target`** — the common case, not an exception. Of the 16 partial
  runs, **15 record a named `unavailable_sources` entry** (the sixteenth is an RLA run, which
  records none at all), so the explanation is present in the log for 15 of 16 and simply never
  reaches the UI.

**Root cause.** Confirmed: the data exists, the UI has no field to read.

**Severity.** Major (honesty rule §0.2: `partial` must be explainable).

**Proposed fix.** Add `status_reason` to `_handle_info` and `history()`, composed from
`termination_reason` + `unavailable_sources`; include named failures in RLA `run_finished`;
render a chip popover listing reasons and a "why" line in the thread summary.

**Approach & alternatives.**
- *Chosen:* one short human string plus a structured list, both small.
- *Rejected:* sending the whole `failed_sources` mapping to the browser — it can contain
  provider error text with URLs; only names + a redacted short message.

**Risk.** Error strings may contain keys or URLs; everything user-visible must pass through
`redact_text` (`webapp.py:108`) — currently applied to `error` only.

**Proof.** Test: a simulated failed source yields `status="partial"` and
`status_reason` naming that source; RLA run_finished includes `failed_sources` names; a copy
test asserts the redaction function is applied to `status_reason`.

---

### A-05 — Retrieval/selection quality: not measured (report only, out of scope)

**Symptom.** Weak matches in selected sets (the owner's 20-paper QA note).

**Evidence.** `docs/master.md:37-66` records the 20-paper QA and states the suite
"does not measure live-paper relevance". The corresponding runs exist:
`Q01-deep`…`Q10-deep` (381-382 events each) and `Q01-quick`…`Q10-quick` (121-126 events
each), all quick runs ending in `completed_with_partial_sources`.

**Root cause.** Not a defect: retrieval relevance has no ground truth in the repo, and
`Project_changes.md` §9 puts relevance logic out of scope.

**Severity.** Minor (reporting only).

**Proposed fix.** None in code. Add a standing, visible limitation note in the Library and
answer footer: "Retrieval quality is pending human review"; never show accuracy percentages.

**Approach & alternatives.** Rejected: building a relevance eval — it needs hand-labelled
data the repo does not have (`eval/ground_truth.py:assess_reference_set` refuses to report
metrics for a set that was not hand-labelled).

**Risk.** If the UI shows counts it may read as quality. Mitigation: neutral wording +
"selected", never "best"/"relevant".

**Proof.** Copy test forbidding `accurate|accuracy|verified true|proven` in rendered UI
strings; existing honesty tests unchanged.

---

### A-06 — Config/limits drift: the UI silently raises the documented daily budget

**Symptom.** The advanced field says 100 model requests by default, while the backend's
configured daily cap is 15 and the documented free tier is ~20/day/model.

**Evidence.**
- Backend defaults: `paper_limit=20` (`webapp.py:55`, `MAX_LIVE_PAPER_LIMIT=20` at `33`),
  `provider_wait_seconds=300` (`webapp.py:56`), `llm_request_budget=100` (`webapp.py:57`).
- `/api/config` returns the **configured** value: `"llm_request_budget": settings.llm_daily_budget`
  (`webapp.py:145`), whose default is 15 (`RLA_LLM_DAILY_BUDGET`, `.env.example`).
- The UI overwrites it upward: `setBudget(Math.max(100, config.llm_request_budget || 100))`
  (`main.jsx:210`). With a configured 15, the field shows **100**.
- Submitting sends 100 (`main.jsx:225`), and the RLA path applies it as the run's
  `llm_daily_budget` (`webapp.py:336-343`). So the UI overrides the operator's cap for that
  run, and the user sees no warning.
- Documented quota: "Free-tier quota is per day, per model (~20 req/day observed)"
  (`README.md:239`) and "per day, per model (~20 req/day)" (`README.md:404`).
- Other bounds are consistent: `paper_limit` 2..20 in both (`webapp.py:55` vs
  `main.jsx:259`), cooldown 0..3600 (`webapp.py:56` vs `main.jsx:260`), concurrency 1..8
  (`webapp.py:45` vs `main.jsx:265`), source limit 2..5 (`webapp.py:46` vs `main.jsx:264`).
- Server validation is strict, but the response shape is not rendered: `400` with
  `fields` (`webapp.py:803-806`) is reduced to `body.error` (`main.jsx:28`).

**Root cause.** Confirmed: `Math.max(100, …)` deliberately floors the field at 100, and field
errors are dropped by the API client.

**Severity.** Major (cost/quota; silent override of an operator setting).

**Proposed fix.** Use the value verbatim; display "configured daily cap: 15" next to the
field; block values above the configured cap unless the user opts into an explicit override
that states the consequence; render `fields[].msg` inline.

**Approach & alternatives.**
- *Chosen:* server value is the default and the warning threshold; override is allowed but
  explicit and labelled.
- *Rejected:* hard-capping at 15 — the FODS live path legitimately needs more LLM calls, and
  the backend already allows up to 1000.

**Risk.** A user who overrides will still hit quota; the backend's per-run budget is a local
cap, not a provider guarantee (documented in `AGENTS.md`). Copy must not imply the field is a
quota guarantee.

**Proof.** Test that `/api/config`'s 15 reaches the input unchanged (currently it would not);
test that submitting above the cap requires the override checkbox; test that a 400 with
`fields` renders one message per field.

---

### A-07 — Citation-integrity claims: one hardcoded `true`, one misleading badge

**Symptom.** The UI can assert "Citation IDs passed validation" when they did not, and labels
a *count* as "verified".

**Evidence.**
- FODS performs a real ID check and emits `citation_validation` with `valid`, `found`,
  `unknown` (`tools.py:1484`-area payload).
- RLA reports stripped ids: `stripped_citations=answer_result.stripped_citations`
  (`webapp.py:416`) — but then emits `brief_saved` with **`citations_validated=True`
  hardcoded** (`webapp.py:428`), without consulting `stripped_citations`. RLA emits no
  `citation_validation` event at all, so the flag is the only "validation" signal it produces.
- UI wording: "Citation IDs passed validation…" (`main.jsx:296`) and the evidence header
  badge `badge(String(evidence.length || papers.length), "verified")` (`main.jsx:299`) — a
  paper count styled as "verified".
- `[C#]` citations have no evidence record (`webapp.py:405-409`), so concept citations are
  never checked against anything in the UI.

**Root cause.** Confirmed.

**Severity.** Major (honesty rule §0.4: "citation check ≠ semantic verification").

**Proposed fix.** Compute `citations_validated = not answer_result.stripped_citations` for
RLA (and include `stripped_citations` in `brief_saved`); replace the "verified" badge with a
neutral "N selected"; add one line of copy: "ID/provenance check only — claim-level support
is not verified"; include concept nodes in evidence (UI-09).

**Approach & alternatives.**
- *Chosen:* derive the flag from data that already exists.
- *Rejected:* emitting a fake `citation_validation` event for RLA — it would claim a check
  that the RLA pipeline does not perform.

**Risk.** `test_fods_webapp.py` may assert `citations_validated is True` for a brief
fixture — if so, that test encodes the bug and must be changed with the reason recorded.

**Proof.** Test: a stripped-citation fixture yields `citations_validated=False` and a
`status_reason` naming the stripped id; copy test forbids "verified true"/"accurate".

---

### A-08 — Brief endpoint: correct containment, missing download semantics, one crash path

**Symptom.** Raw text in a new tab (UI-10); a corrupt log drops the connection instead of
returning an error.

**Evidence.**
- Containment is correct on both sides: filename regex (`webapp.py:32`), workspace check
  (`213-214`), 409 on existing output (`215-216`), read-side `is_relative_to(briefs_dir)`
  (`592`).
- Response: `text/markdown; charset=utf-8`, no `Content-Disposition`, no size limit
  (`704-713`).
- `brief()` calls `read_events(path)` unguarded (`584-587`); `read_events` raises
  `ValueError` on a malformed line (`events.py:62-63`); `do_GET` has no `try` (`650-726`) →
  the handler raises, the socket closes, the browser shows a network error.

**Root cause.** Confirmed.

**Severity.** Minor.

**Proposed fix.** `?format=json` → `{run_id, markdown, citations, sources}`; `?download=1` →
`Content-Disposition: attachment`; wrap the read in try/except → 500 JSON with a stable
message; cap the response body (e.g. 2 MiB → 413).

**Approach & alternatives.**
- *Chosen:* one endpoint, two representations, no new route.
- *Rejected:* a separate `/brief.json` route — more surface for no gain.

**Risk.** `_json` pipes everything through `safe_value` (`webapp.py:632`), which redacts
secret-looking strings and would mangle Markdown/citations. The JSON variant must serialise
plainly (the file is already generated locally), and that exception must be documented in
code and tested.

**Proof.** Tests: 200 + header for `?download=1`; 404 + JSON for a run with no brief; 500 +
JSON for a corrupt log; 413 for an oversized body.

---

### A-09 — Persistence: one corrupt line hides a run; history is O(all events) per call

**Symptom.** A run silently disappears from history; `/api/history` slows as logs accumulate.

**Evidence.**
- Append-only JSONL per run (`webapp.py:219`; `events.py:47-49`), which is the right shape.
- `read_events` raises on any malformed line (`events.py:62-63`).
- `history()` catches that and `continue`s (`webapp.py:499-502`), so the run vanishes from
  the Library with no trace. `brief()` does not catch it (A-08).
- `history()` re-reads and re-parses **every** log on every call (`webapp.py:494-536`) —
  82 runs, up to 382 events each, triggered on mount and after every run
  (`main.jsx:66-74`, `101-102`).
- Shared artifacts (`data/graph/graph.json`, `data/extractions.jsonl`) are rewritten by every
  RLA run; only RLA runs are serialised, by `LiveCollectionLock` (`webapp.py:362`).
- README documents a schema-v1 vs schema-v2 graph mismatch (`README.md:103-104`).

**Root cause.** Confirmed for the corrupt-line and complexity issues; the shared-artifact
model is intentional.

**Severity.** Minor.

**Proposed fix.** Add `read_events(strict=False)` returning `(events, skipped)`; keep strict
as the default so existing callers/tests are unaffected. History keeps the run with
`status="interrupted"` and `warnings: n`. Cache the history index keyed by
`(path, mtime, size)`.

**Approach & alternatives.**
- *Chosen:* tolerant reader + cached index, no format change.
- *Rejected:* rewriting logs to repair them — mutates first-party evidence.

**Risk.** Caching can serve stale status for a run that just finished; invalidate by mtime,
which the write path already changes.

**Proof.** Test with a corrupt line: `history()` lists the run with a warning count;
`brief()` returns 500 JSON; strict mode still raises; a micro-benchmark asserts the second
`/api/history` call does no file reads.

---

### A-10 — Concurrency: Stop does not exist, and it would be a no-op for the default mode

**Symptom.** There is no Stop button (`docs/master.md` / §A-10 note "no Stop button is
visible today"), and the one cancellation endpoint that exists cannot stop an RLA run.

**Evidence.**
- `DELETE /api/runs/<id>` exists and sets `handle.cancel_event` (`webapp.py:814-824`).
- The FODS path passes that event into `_execute` (`webapp.py:270`) and the runtime checks it
  on every scheduling iteration (`runtime.py:635-640`), cancelling queued and running tasks.
- **The RLA path never sees it.** `_execute_research_pipeline` (`webapp.py:326-485`) takes no
  `cancel_event` and contains no cancellation check; `cancel_event` appears in only three
  places in the whole file (`95`, `270`, `823`). So `DELETE` on an RLA run returns 202
  `cancellation_requested` and the pipeline continues to completion — a false confirmation.
- The frontend never calls `DELETE`: no `method: "DELETE"` anywhere in `main.jsx`.
- Double submit within one tab is prevented by `active` (`main.jsx:111`) and the
  `Idempotency-Key` (`main.jsx:114`, server `webapp.py:203-208`). Two tabs are not
  prevented; FODS has no global lock, so two live runs can share the SQLite cache. RLA is
  serialised (`webapp.py:362`) and the second run fails with `already_running`
  (`webapp.py:457-467`).
- `workerAssignmentsAvailable` is hardcoded `false` (`shell-core.js:74`), and
  `task_started` records `attempt` and `stack` but no worker slot (`runtime.py:441-451`).

**Root cause.** Confirmed: cancellation was implemented for the FODS runtime only, and the UI
never wired it up.

**Severity.** Major.

**Proposed fix.** Wire a Stop button to `DELETE`, and make RLA cancellable cooperatively:
check the event between pipeline items, and on cancel stop consuming the async generator and
emit `run_finished(termination_reason="cancelled")` + `status="cancelled"`. If RLA
cancellation is judged out of scope, then **hide** Stop for RLA with the reason "this run
type cannot be cancelled" — never show a button that lies. Add `worker_slot` to
`task_started` (in-flight count at dispatch) so the Lab's worker pool shows recorded data and
`workerAssignmentsAvailable` becomes true, with an explicit caption that the slot is an
assignment order, not a recorded worker id.

**Approach & alternatives.**
- *Chosen:* cooperative cancel for both paths; it is UI-visible, cheap, and honest.
- *Rejected:* killing the thread — cannot be done safely in Python, and would leave
  half-written artifacts.
- *Rejected:* UI-only Stop (abandon the stream) — the run keeps burning quota; dishonest.

**Risk.** Cancelling mid-pipeline leaves partial graph/extraction state; both are
append-only or derived, and the next run reuses them (`extracted: 0, reused: 10` is normal),
so this is acceptable but must be stated. Touches shared pipeline code — approval needed.

**Proof.** Test: `DELETE` during a slowed RLA run yields `run_finished(termination_reason=
"cancelled")` within N seconds and `GET /api/runs/<id>.status == "cancelled"`; UI test that
Stop is rendered only when cancellable and shows the confirmation state.

---

### A-11 — Security: absolute paths leak to the browser; no Origin/Host validation

**Symptom.** The Trace JSON pane shows local absolute paths. Any page in the same browser can
attempt requests to the local API.

**Evidence.**
- **Path disclosure (confirmed).** The RLA `graph` stage payload contains
  `"path": "D:\\Research_AI_Agent-fods\\data\\graph\\graph.json"` and the `done` payload
  contains `extraction.store`; both are emitted to the browser (`webapp.py:368-375`) and
  rendered verbatim in the payload pane (`main.jsx:318`). This is real data from
  `efee736eb669`.
- Hardening that is present: loopback default (`cli.py:1026-1031`), CSP
  `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src
  'self' data:; object-src 'none'; base-uri 'none'` (`webapp.py:623-627`), `nosniff`,
  `no-referrer` (`621-622`), 64 KiB body cap (`643-644`).
- No CORS headers and **no `Origin` check** on `do_POST` (`webapp.py:784-812`); no `Host`
  check. Cross-origin *reads* are blocked by the absence of CORS, but a simple cross-origin
  POST can still be attempted (JSON bodies require a preflight, so this is mitigated in
  practice), and DNS rebinding is not addressed — **hypothesis**: a rebound hostname pointing
  at 127.0.0.1 would pass the `Host` check because there is none.
- Secrets are handled correctly: `/api/config` exposes booleans and model names only
  (`webapp.py:136-148`); event payloads pass `safe_value` (`events.py:44`); errors pass
  `redact_text` (`webapp.py:108`). No key is ever sent to the browser in the code I read.
- CSP `style-src 'self'` blocks inline `style="…"` attributes written in HTML; CSSOM
  assignments from JS are unaffected. New UI code must not rely on inline style attributes.

**Root cause.** Confirmed for the path leak and the missing Origin/Host checks; the
rebinding consequence is a hypothesis.

**Severity.** Major (information disclosure; the security checklist item "error messages
leaking paths" is met by payloads instead of errors).

**Proposed fix.** (1) Relativise or strip workspace-absolute paths before emit (one helper
applied to `stage_payload`); (2) reject requests whose `Origin` is present and not in an
allow-list (`http://127.0.0.1:<port>`, `http://localhost:<port>`, plus the Vite dev origin
from config); (3) validate `Host`; (4) keep the existing CSP.

**Approach & alternatives.**
- *Chosen:* a `safe_value` sibling for paths + an Origin guard, because both are small and
  testable.
- *Rejected:* removing `stage_payload` wholesale — it is the data the Lab needs.
- *Rejected:* an auth token — overkill for a local single-user tool, and it would have to be
  injected into the served HTML.

**Risk.** The Origin guard can break the Vite dev proxy (`vite.config.js:14` proxies `/api`
to 8765, so the browser's Origin is `http://127.0.0.1:5173`). Allow it explicitly via an env
var, defaulting to the loopback pair.

**Proof.** Tests: `Origin: http://evil.example` POST → 403; same-origin → 202; a scan over
all 82 stored logs asserts no event payload contains the `data_dir` absolute prefix; a Host
mismatch → 403.

---

### A-12 — Error UX: failures are swallowed or unactionable

**Symptom.** A failed request shows one line with no next step; a dropped stream changes
nothing on screen; the brief tab shows a bare 404 JSON body.

**Evidence.**
- `api()` throws only `body.error` (`main.jsx:28`), discarding the `fields` array the server
  provides (`webapp.py:803-806`).
- Errors render in exactly one place per page: in-form (`main.jsx:275`) or above the page
  (`main.jsx:392`). No retry action, no error boundary.
- `stream.onerror` does nothing visible unless the stream is already CLOSED
  (`main.jsx:105-107`); `refreshHistory().catch(() => {})` swallows failures
  (`main.jsx:101-102`).
- Screenshot 13 is the raw browser rendering of the brief endpoint — the "error UX" for a
  missing brief is the browser's own plain-text viewer.

**Root cause.** Confirmed: no error taxonomy and no recovery affordances.

**Severity.** Major.

**Proposed fix.** Typed error mapping (`code`, `message`, `detail`, `recover`), inline field
errors, a stream-status banner with Retry, per-page empty/error states with a primary action,
and a top-level error boundary so a render crash does not blank the app.

**Approach & alternatives.**
- *Chosen:* map HTTP codes + known server messages to one small table; no library.
- *Rejected:* a toast-only approach — toasts disappear and do not carry next steps.

**Risk.** Over-reporting transient reconnect blips; debounce the banner by ~2 s.

**Proof.** Test matrix over the documented failures (400 fields, 404 run, 404 brief, 409
duplicate output, 403 origin, stream 404) asserting a message **and** an action for each.

---

### A-13 — Performance: per-event full copies, unvirtualised lists, unbounded buffers

**Symptom.** The biggest recorded run has 382 events; the UI recomputes and re-renders over
all of them on every event and every keystroke.

**Evidence.**
- Per SSE message the client does `setRun({...next})` **and** `setEvents([...next.events])`
  (`main.jsx:96-97`) — two renders and two O(n) copies per event.
- Trace filters `events.slice(0, cursor).filter(...)` inside `useMemo` keyed on every
  keystroke (`main.jsx:313`); every visible row is a DOM node (`main.jsx:317`).
- Lab re-derives the whole snapshot per cursor tick (`main.jsx:364`), and playback advances
  one event every 650 ms (`main.jsx:358-362`) — 382 events ≈ 4 minutes of full re-derivation.
- `deriveSnapshot` scans all visible events on every call (`shell-core.js:13-81`).
- `history()` parses every log per call (A-09).
- `RunManager.runs` never evicts (A-02).
- Previously built bundle in this worktree (untracked): `dist/assets/index-dYS1PXQI.js` =
  269,441 B, `index.css` = 23,340 B. No code splitting.

**Root cause.** Confirmed: no incremental model, no virtualisation.

**Severity.** Minor (382 events is survivable today, but it is the stated target scale).

**Proposed fix.** One reducer dispatch per animation frame batch; incremental snapshot
(apply the new event to the previous snapshot instead of rescanning); memoised
`describeEvent` per event id; fixed-height virtual list for Trace rows (±10 window); cap
buffers and evict finished handles; cache the history index.

**Approach & alternatives.**
- *Chosen:* incremental snapshot + windowing, no new dependency.
- *Rejected:* `react-window`/`virtua` — a dependency for ~40 lines of windowing maths on a
  fixed row height.

**Risk.** Incremental state is harder to test than a pure fold. Mitigate by keeping the pure
fold as the reference and asserting `fold(events) === replayIncremental(events)` for the three
golden logs.

**Proof.** Benchmark: first paint of the 381-event trace < 100 ms with < 60 DOM rows;
`fold === incremental` on all three goldens; a 5 000-event synthetic log stays interactive.

---

### A-14 — Tests and docs drift: three different test counts, none verifiable here

**Symptom.** The repo states three different test totals, and none of the documented commands
can be verified in the current tree.

**Evidence.**
- `README.md:499` — `python -m pytest tests/ -q    # 668 passed`.
- `docs/master.md:37` and `:65` — "808 tests passed and one skipped"; `docs/master.md:63-64`
  — "the historical closeout records 797 tests passed at that commit".
- Static count of test functions across `tests/*.py` at `3081afb`: **742**
  (`grep '^\s*(async )?def test_'`). This is a static count, not a collected count:
  parametrisation and skips change the real number.
- **None of the documented commands runs in this worktree** (§0.2): `python -m fods.cli` fails
  to import, `npm run build` has no `package.json`.
- Test-quality risk for this redesign: `tests/test_fods_frontend_shell.py:84-101` asserts
  literal source strings (including `graphLayout(tasks)` at line 98 and
  `prefers-reduced-motion` at line 100), and `:126-131` asserts
  `workerAssignmentsAvailable: false` — a test that **locks in** the missing worker data.
  `test_vendored_d3_generates_curved_svg_dependency_paths` (`:137-161`) tests only the
  vendored d3 files used by the dead legacy shell.

**Root cause.** Confirmed: the totals were written by hand at different times; the frontend
tests assert on source text instead of behaviour, so they cannot survive a rewrite.

**Severity.** Major (a submission cannot claim a number it has not measured).

**Proposed fix.** Restore the tree, run the suite once, and put the measured number in
**one** place (README) with the command, date, and commit; have `docs/master.md` reference it
instead of repeating it. Replace the source-grep frontend tests with behavioural tests (the
Node test for `shell-core` equivalent behaviour moves to vitest, keeping the same synthetic
fixture `tests/fixtures/fods_frontend/demo_data.json`, which is valuable). Delete the
d3-vendor test with the vendor code.

**Approach & alternatives.**
- *Chosen:* behavioural tests + one measured number.
- *Rejected:* keeping the source-text test and shaping the new code to satisfy it — that
  inverts the purpose of the test.

**Risk.** Deleting tests reduces apparent coverage; mitigate by adding real tests in the same
slice and by recording the before/after count in the submission report.

**Proof.** `python -m pytest tests/ -q` output pasted into the submission report with a date
and commit; `--collect-only` count matches the README number; the replaced frontend tests
fail if a view is removed.

---

### A-15 — Packaging: the Docker path is not committed, and one env var is undocumented

**Symptom.** `Dockerfile`, `compose.yaml`, `requirements-docker.lock` exist only as untracked
files in the `main` worktree. A fresh clone of the code branch has no container build.

**Evidence.**
- `git ls-tree -r --name-only codex/research-frontend-5paper-checkpoint | Select-String
  'Docker|compose|requirements-docker'` → **no matches**.
- The untracked `Dockerfile` at the worktree root builds the frontend in
  `node:22-alpine` (digest-pinned), runs `npm ci` from the lockfile, builds with
  `npm run build`, then copies `/workspace/src/fods/web/dist/` into the Python runtime image.
  That matches `vite.config.js:16-21` (`outDir: ../src/fods/web/dist`).
- `stitch_aesthetic_markdown_reader/package.json` pins nothing (`^19.0.0`, `^6.0.0`,
  `^0.468.0`) but `package-lock.json` exists, so `npm ci` is reproducible.
- `.env.example` lists `RLA_LLM_DAILY_BUDGET`, models, providers — but **not**
  `RLA_FODS_ALLOW_GEMINI`, which is read at `webapp.py:140` and `cli.py:123`, `788`, and
  gates the Gemini opt-in for FODS.
- `RUN_ID`/`OUTPUT_NAME`/`data/` are all workspace-relative, so the image's `RLA_DATA_DIR`
  and `PYTHONPATH=/app/src` are consistent with the code.

**Root cause.** Confirmed: the container work was done on `main` and never landed on the
feature branch; one env var was added in code only.

**Severity.** Major (the definition of done requires "Docker builds"), minor for the env var.

**Proposed fix.** Commit the four packaging files to the working branch, build once and record
the result; add the missing env var row with its default and effect; add a `docker` smoke
step to the submission checklist.

**Approach & alternatives.**
- *Chosen:* commit the existing, reviewed Dockerfile rather than designing a new one.
- *Rejected:* building in CI only — the requirement is a local, reproducible build.

**Risk.** `npm ci` needs network; if the lockfile and the branch's `package.json` drift, the
build fails loudly (which is the point). Base images are digest-pinned, so no surprise drift.

**Proof.** `docker build` + `docker run` + `curl -s http://127.0.0.1:8765/api/health` returns
`{"ok":true}`; the container serves the built UI at `/`; `.env.example` diff shows the new
row.

---

## 4. What this audit could not verify

Stated explicitly, per the honesty rules:

1. **Test suite result.** Not run (§0.2). Every "test passes" claim in the repo is unverified
   by me, including the 668/797/808 figures.
2. **Lint result.** `ruff` not run against `src/fods`.
3. **Production build.** `npm run build` not run on the branch.
4. **Browser reproduction.** The app could not be served, so screenshots 01-13 were not
   reproduced; every UI finding above is traced to code and/or recorded log data instead.
5. **Live provider behaviour** (429s, DBLP bot-check, Ollama availability). Only inferred from
   `termination_reason` distribution and recorded payloads; no live request was made.
6. **DNS-rebinding exploitability** (A-11) — hypothesis, not demonstrated.
7. **Semantic quality of answers** — explicitly out of scope and unmeasured (§A-05).

---

## 5. Cross-cutting conclusions

1. **The backend is more honest than the frontend.** The runtime records reasons, source
   failures, durations and retry counts; almost none of it reaches the user. Most "UI" defects
   are presentation of data that already exists — the exceptions are `status`, `worker_slot`,
   RLA durations, and RLA cancellation.
2. **Two pipelines share one shell without a label.** UI-07, A-03, and the replay-identity
   half of UI-08 are the same bug: the system never says *what kind of run* it is showing.
3. **The Lab is the product.** It is also the only surface that is empty in the default mode.
   Fixing UI-07 is not a polish item; it decides whether the project demonstrates its thesis.
4. **Only two things genuinely need new backend data**: run status/reason (A-01/UI-08) and
   event enrichment (UI-11). Everything else is already recorded.

---

## 6. Reproduction appendix

Commands used, in order, from `D:\Research_AI_Agent-fods`:

```powershell
git rev-parse --abbrev-ref HEAD                      # main
git ls-files src/fods | Measure-Object               # Count 0
git log -1 --format='%h %ad %s' --date=short codex/research-frontend-5paper-checkpoint
# 3081afb 2026-11-15 Add detailed 20-paper pipeline QA report
.\.venv\Scripts\python.exe -m fods.cli --help        # No module named fods.cli
Test-Path stitch_aesthetic_markdown_reader\package.json   # False

# read-only export used for every citation
git archive --format=zip -o "$env:TEMP\opencode\fods-audit\src.zip" `
    codex/research-frontend-5paper-checkpoint
Expand-Archive "$env:TEMP\opencode\fods-audit\src.zip" `
    -DestinationPath "$env:TEMP\opencode\fods-audit\tree" -Force

# recorded-run evidence
Get-ChildItem data\fods\runs\*.jsonl | ForEach-Object { ... }   # engine / mode / event kinds
# 82 logs; 3 RLA (plan_validated=0, research_progress=31/53/50); 79 FODS
Get-Content data\fods\runs\Q01-deep.jsonl   # 381 events, seq 1..381, no gaps
Get-Content data\fods\runs\8c5a5ba36606.jsonl
# 2 events: plan_received, plan_rejected — no run_finished (zombie)
```

Frontend/back-end facts asserted above and their exact locations (commit `3081afb`):
`main.jsx:28,49-53,92-95,105-107,111,138,143,150,152,171-174,181-184,190,204,210,216-218,
237,242-290,296-300,307-320,322-336,346,358-364,368,370,385,391,393-396`;
`webapp.py:33,36-57,86,91,105-110,124,136-148,160-161,192-198,203-227,236-324,326-485,
447,491-536,538-558,581-594,597-607,613-627,643-644,650-726,738-782,784-812,814-824,
829-841`; `runtime.py:37-52,100-147,200-238,280-308,441-451,486,632-640,700-723,780-801,
819-885`; `events.py:15-24,39-52,55-64`; `shell-core.js:13-81,87-92`;
`tests/test_fods_frontend_shell.py:84-101,107-131,137-161`;
`README.md:103-104,239,404,499`; `docs/master.md:37,63-66`.
