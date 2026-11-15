# AGENT_PROMPT.md — kickoff instructions for the coding agent (opencode)

> Paste the **"Kickoff prompt"** section below into opencode as your first message.
> Put these in the repo root first: `Project_changes.md`, this file, and the folder
> `ui-review/` as `docs/ui-review/` (screenshots).
> The repo's existing `AGENTS.md` stays as-is; the agent must read it and follow it.

---

## Kickoff prompt (copy from here)

You are working in the FODS Research Agent repository. Your job has three parts:
**(1)** audit the pipeline and the frontend, **(2)** redesign the frontend from scratch,
**(3)** leave the project ready to submit.

### Step 0 — Read, do not edit
Read in this order, and do not modify any file until Gate A is approved:
1. `AGENTS.md`  2. `docs/master.md`  3. `README.md`  4. `Project_changes.md` (your requirements)
5. Every image in `docs/ui-review/` (13 files; names describe them; `REF-*` are style
   references, not bugs).
6. The code: backend entry (`python -m fods.cli serve`), the API/SSE layer, event schema, run
   store, brief endpoint, and the whole `stitch_aesthetic_markdown_reader/` frontend.

### Rules you must follow
- **Never guess.** Locate code with search before claiming how it works. Cite `file:line` for
  every claim. If you cannot verify something, label it **hypothesis**.
- **Do not edit anything before Gate A approval.** Reading and running read-only commands is fine.
- `Project_changes.md` is a first draft. You have **full autonomy** to choose a better
  architecture, layout, or colour system, but you must fix every `UI-xx` issue and meet the
  acceptance criteria, and you must **explain any deviation**.
- Respect the honesty rules in `Project_changes.md` §0 (no hiding `partial`/failures, no claiming
  replay is live concurrency, no accuracy claims, citation check ≠ semantic verification).
- The frontend must not schedule work or call providers/LLMs. Secrets never reach the browser.
- Keep backend changes **additive and backward compatible**; old saved runs must still replay.
  Keep `--mode simulate --planner fixture` working.
- Small steps. One slice at a time. Run the checks after **each** slice (see below). Do not
  stack five features before testing.
- If a tool call or command fails, read the error, fix the cause, retry once; if still stuck,
  stop and report instead of looping.
- No new dependency without: one-line reason, pinned version, licence noted, and confirmation
  that `npm ci` and the Docker build still work.
- Do not touch the scheduler algorithms or retrieval/relevance logic (out of scope).
- Never paste secrets, API keys, or `.env` contents into any output or file.

### Phase 1 — Audit and diagnosis (read-only) → produce `docs/audit/AUDIT_FINDINGS.md`
For each `UI-xx` in `Project_changes.md` §3 **and** each audit area `A-xx` in §5, write a finding:

| Field | Content |
|---|---|
| ID / title | e.g. `UI-08 Stale run status chip` |
| Symptom | what the owner sees (reference the screenshot file) |
| Evidence | `file:line`, command output, or a reproduction — not opinion |
| Root cause | confirmed, or marked hypothesis |
| Severity | blocker / major / minor |
| Proposed fix | the concrete change |
| Approach + alternatives | why this one; what else you considered |
| Risk | what could break |
| Proof | the test that will show it is fixed |

Also reproduce what you can: run the app in simulate mode, run the test suite, run
`npm run build`, and record the baseline results (pass/fail counts, warnings).
Pay special attention to:
- **UI-07:** confirm which pipeline each execution mode runs and which events each emits.
  Explain exactly why the Lab was empty, and recommend option (a) phase-graph or (b) explanatory
  empty state, with reasons.
- **UI-08:** find every place that holds "current run" or "status" state; list the sources of
  truth; confirm why the chip said `starting` and why its ID differed from the selected run.
- **A-06:** compare UI defaults (20 / 300 / 100) with backend config and documented quotas.
- **A-14:** reconcile test counts and verify that each documented command works.

### Phase 2 — Design proposal → produce `docs/FRONTEND_DESIGN.md`
Keep it short and decision-oriented (aim for ≤ 4 pages):
1. Layout and navigation (sidebar, thread, composer with `+` menu, evidence panel, brief
   overlay) with a simple ASCII or Mermaid wireframe.
2. Colour/type/spacing/motion tokens, light + dark.
3. Component tree and folder structure; state model (single `activeRunId`, derived status,
   one SSE manager).
4. Lab design: DAG layout algorithm, queue/worker/state-map/stack visuals, playback model,
   LIVE vs REPLAY, concept captions, plus the chosen answer for RLA runs (UI-07).
5. Trace design: waterfall columns, grouping, filters, detail tabs, summary bar, virtualisation,
   in-chat status lines. Where the one-line `summary` comes from (backend field vs frontend
   mapper) and why.
6. Backend changes required (list, each additive; schema of new fields).
7. Test plan (unit, component, browser smoke) and the slice order with a "definition of done"
   per slice.
8. Any deviation from `Project_changes.md` and why.

### ⛔ GATE A — STOP HERE
Post a **short summary** (not the whole files) in chat:
- number of findings by severity,
- top 5 problems with cause → fix → approach,
- the design in 10 lines,
- anything that needs a decision from the owner (list as numbered questions).

**Then stop and wait for the owner to reply "approved" (or with changes). Do not edit code
until then.**

### Phase 3 — Implementation (only after approval), in slices
Suggested order (you may reorder with a reason):
1. **Foundation:** tokens, theme, app shell (sidebar + thread + composer), API client, typed
   store with single `activeRunId`, SSE manager. *(fixes UI-01, UI-03, UI-05, UI-08 groundwork)*
2. **Composer `+` menu:** mode, agent configuration, advanced parameters with validation.
   *(UI-02, UI-04)*
3. **Backend additions:** event `summary`/`phase`/`class`/`severity`/`duration_ms`,
   authoritative run status + `status_reason`, brief JSON endpoint, parameter validation,
   cancel (if feasible). Add backend tests. *(UI-08, UI-10, UI-11 support, A-06)*
4. **Thread + run lifecycle:** live "working" status lines, collapse to "Worked for …",
   answer card, status chip, New investigation, Stop. *(UI-05, UI-08, UI-11)*
5. **Answer + evidence:** interactive citation chips, two-way highlight, scroll-into-view,
   `[C#]` handling. *(UI-09)*
6. **Brief overlay:** rendered Markdown, copy/download, sanitised. *(UI-10)*
7. **Trace:** waterfall/timeline, filters, detail pane, summary bar, virtualised list.
   *(UI-11)*
8. **FODS Lab:** DAG, queue + workers + state map, stacks, playback, concept captions, RLA-run
   handling. *(UI-07)* — this is the core of the project; spend the most care here.
9. **Audit fixes** not already covered, in severity order (blockers first).
10. **Cleanup:** remove the old frontend and dead code; accessibility pass; empty/error states
    everywhere; docs and screenshots; Docker.

**After every slice, run and report:**
```
python -m pytest tests/ -q
python -m ruff check src/
cd stitch_aesthetic_markdown_reader && npm run build && npm test   # if tests exist
```
Then commit (one commit per slice, clear message) and post a **3-line status**: what changed,
what passed, what's next. If anything regressed, fix it before moving on.

If during implementation you discover a **new** problem or need a decision that changes scope,
stop and ask. Do not silently expand scope or silently drop a requirement.

### Phase 4 — Submission readiness
Do all of `Project_changes.md` §7, then write `docs/SUBMISSION_REPORT.md`:
what changed; every audit finding with status (fixed / deferred + rationale / accepted risk);
test and build evidence; before/after screenshots for every `UI-xx`; known limitations
(preserve the original honest framing: retrieval quality pending human review); 5-minute demo
instructions.

### ⛔ GATE B — final check
Before declaring done, verify on a **fresh clone** (or clean checkout): install, build,
`fods run` simulate, `fods serve`, open the UI, run a deterministic demo, click a citation, open
the brief overlay, open the Lab and Trace, press New investigation. Report results honestly,
including anything that did not work. Do not claim "ready" unless every step passed.

### Definition of done
Every `UI-xx` fixed with evidence · audit findings all resolved or explicitly deferred with the
owner's approval · tests, lint, build green · old frontend removed · docs updated · Docker builds ·
`docs/SUBMISSION_REPORT.md` written · working tree clean.

Begin with Step 0 now, then Phase 1. Do not edit files until Gate A is approved.

## (end of kickoff prompt)

---

## Owner notes (not for the agent)

**Using opencode with DeepSeek V4.1 Flash**
- A fast model works best with small, checkable steps. This prompt is built that way: hard gates,
  one slice at a time, tests after every slice.
- Start in opencode's **plan / read-only mode** if your version has one, send the kickoff prompt,
  and let it finish Phase 1–2. Switch to the build mode only after you reply "approved".
- If the agent loses track in a long session, start a fresh session and tell it:
  "Read `Project_changes.md`, `docs/audit/AUDIT_FINDINGS.md`, `docs/FRONTEND_DESIGN.md`, and
  `git log`; continue from the next unfinished slice." The docs act as its memory.
- Flash-class models can overstate success. Spot-check: ask it to show the test output, and open
  the app yourself after slices 4, 7, and 8.
- If it tries to do Phase 3 early, reply: "Stop. Gate A is not approved yet."

**What to send at Gate A:** reply "approved", or give numbered answers to its questions. If you
want changes, say which UI item or design decision to revise.
