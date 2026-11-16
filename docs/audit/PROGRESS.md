# PROGRESS — studio redesign

**Branch:** `feature/studio-redesign` · **Base:** `codex/research-frontend-5paper-checkpoint` @
`3081afb` · **Worktree:** `D:\fods-studio-redesign` · Gate A approved 2026-11-15 (with amendments).

This file is the durable memory of the work. Update after every slice.

## Decisions in force (from Gate A approval)

| # | Decision | State |
|---|---|---|
| 1 | Separate worktree + new branch; own venv; `main` staging untouched | done (`D:\fods-studio-redesign`, venv at `.venv`) |
| 2 | UI-07 = option (a) labelled phase graph + "Run the deterministic demo" chip in the empty thread | planned (slice 8 + slice 1) |
| 3 | `vitest`, `@testing-library/react`, `jsdom` pinned; Playwright dev-only via `npm run test:e2e`, never in Docker | done (slice 1; exact pins, licence-clean) |
| 4 | RLA cooperative cancel, minimal diff; stop and ask if invasive | **done** (slice 4; the diff stays in `webapp._execute_research_pipeline`, `src/rla` untouched) |
| 5 | Budget = configured cap verbatim + explicit override, enforced server-side with `fields` + stable `code`; remove `webapp.py:57` default of 100 | **done** (`8cd8af1` + slice 2; server returns `code=budget_override_required`, composer states the cap and needs a tick) |
| 6 | Backend one-liners + single `describeEvent()` fallback; redacted, ≤90 chars, no raw JSON/paths | **done backend** (`fods/event_meta.py`; frontend fallback is slice 7) |
| 7 | Delete legacy shell only in slice 9, after green behavioural tests; keep `tests/fixtures/fods_frontend/demo_data.json` | planned (slice 9) |
| 8 | Copy Docker files; add `RLA_FODS_ALLOW_GEMINI`; run real build or write NOT VERIFIED | planned (slice 9) |
| A | `abstained`: no new abstention logic; remove from enum/docs unless the answer stage already exposes a flag | **answered:** no flag exists anywhere in `src/` (only the prompt line `tools.py:298`) → removed from the UI enum, no badge, docs unchanged because they never listed it |
| B | Path leaks: relativise on emit **and** sanitise at the serve layer; old logs replay with identical semantics, only redaction differs; scan test over a fixture copy | planned (slice 3b); the UI already redacts its own fallbacks |
| C | §6 backend list extended with A-02, A-03, A-07, A-08, A-09, A-11 | **done** — rows 13-18 added, row 12 rewritten |
| D | A-01 `finally` in `runtime.py` approved; no queue/ordering change; update `test_fods_runtime.py` deliberately | planned (slice 3a) |
| E | Server `?after=<lastSeq>`: add additively if absent | **answered:** already supported at `webapp.py:745` (falls back from `Last-Event-ID`), no server change; the client uses it |
| F | Markdown renderer: React text nodes only, `http(s)` links only, XSS tests | planned (slice 6) |
| G | "24 tasks" → 26 in design doc examples | **done** (before approval) |

## Slices

| # | Slice | Status | Commit | Gate |
|---|---|---|---|---|
| 0 | Step 1: worktree, baseline, citation spot-check, fixtures | **done** — see `BASELINE.md` | Step 1 commit | pytest 808 passed / 1 skipped · ruff clean · build green |
| 1 | Foundation: tokens, theme, shell (sidebar/thread/composer), store, SSE manager | **done, accepted** | `dcad428` | pytest 809+1 · ruff clean · build green · vitest 43 · Playwright 2 | reviewed |
| 1.1 | Owner review fixes: neutral copy, footer, shared column, e2e isolation, contrast, 768 layout, N-shortcut, recents, CSP assertion | **done** | `fix(ui)` commit | pytest 813+1 · ruff clean · build green · vitest 83 · Playwright 4 | — |
| 2 | Composer `+` menu, mode, config, advanced validation, budget | **done** | `feat(ui)` commit | pytest 817+1 · ruff clean · build 24.15 kB css / 275.99 kB js · vitest 112 · Playwright 5 | — |
| 3a | Backend for UI: enrichment, `pipeline`, status, terminal guarantee, brief JSON, codes | **done** | `feat(backend)` commit | pytest 838+1 · ruff clean · replay of the golden log byte-identical | - |
| 3b | Backend hardening: A-02, A-03, A-07, A-08, A-09, A-11 | **done** (A-03 was slice 3a: `pipeline` + `capabilities.rla_live`) | `feat(backend)` commit | pytest 855+1 · ruff clean · 69 stored logs clean · 7 absolute paths → 0 | - |
| 4 | Thread lifecycle: working lines, chip, New investigation, Stop | **done** | `feat(ui)` commit | pytest 858+1 · ruff clean · build 25.19 kB css / 282.59 kB js · vitest 137 · Playwright 7 | — |
| 5 | Answer + evidence: citation chips, scroll, `[C#]` | planned | — | |
| 6 | Brief overlay | planned | — | |
| 7 | Trace: waterfall, filters, detail, virtualisation, in-chat lines | planned | — | |
| 8 | Lab: DAG, queue, workers, stacks, playback, RLA phase rail | planned | — | **STOP for review** |
| 9 | Cleanup, a11y, docs, screenshots, Docker | planned | — | |

## Slice 1 detail (what the owner should judge)

**Built:** design tokens (light + dark + system preference + reduced motion), the app shell
(sidebar with nav, recents and connection state; thread; composer), a reducer store, one SSE
manager for the whole app, and Vitest/Testing Library/jsdom tests. `Trace`, `Lab` and `Library`
are readable in this slice but deliberately minimal — slices 7 and 8 replace them.

**Verified on the served build** (`fods serve`, port 8877, strict CSP): 2 Playwright checks pass,
`consoleErrors: []`, zero `[style]` attributes, demo completes with 114 events. Screenshots in
`docs/audit/screenshots/` (empty + completed × light + dark).

**Gate numbers:** pytest `809 passed, 1 skipped` (was 808+1: the source-grep test became two
structural CSP tests); `ruff check src/ tests/` all checks passed; vite build 1602 modules,
0.97 kB html / 19.50 kB css / 260.17 kB js; vitest 43 passed in 6 files; Playwright 2 passed.
Playwright browsers were downloaded here (chromium 1255); the tool stays a devDependency and is
not in the Docker image.

**Additions not in the design doc:** `FODS_API_PORT` selects the Vite dev proxy target (8765 is
occupied by an existing Docker container on this machine, so local work used 8877);
`test-results/` and `playwright-report/` are gitignored; a one-frame `data-theme-switching`
attribute suppresses colour transitions so a theme switch never shows an unreadable button.

**Deliberately not in this slice:** composer `+` menu / engine / mode controls / advanced
parameters and budget override (slice 2); answer and evidence cards (slice 5); brief overlay
(slice 6); waterfall, filters and detail pane (slice 7); DAG, queue, worker pool, stacks,
playback and the RLA phase rail (slice 8); Stop (slice 4); deletion of the legacy shell and
vendored d3 (slice 9).

**Layout note:** `npm run build` writes `src/fods/web/dist/`, which `fods serve` prefers. `dist/`
stays gitignored, so the Docker stage and local `npm run build` remain the only producers.

## Slice 1.1 detail (owner review fixes)

Ten items, all applied in this worktree. Measured evidence, not assertions:

1. **Neutral empty copy.** `Ask a question the record can prove.` → `What should we investigate?`
   plus one factual line (`Every panel on this page reads from the events a run records.`).
   `src/test/copy.test.js` forbids `prove|proves|proved|proven|proof|proofs|verify|verifies|verified|accurate|accuracy|guarantee|guarantees|guaranteed`
   across every `src/**/*.{js,jsx}` file except tests, and asserts the new heading.
2. **Footer never wraps at 280 px.** `.sidebar-foot` is `flex-wrap: nowrap` with
   `white-space: nowrap`, the connection label ellipsises, and `ThemeToggle` gained a `compact`
   variant (icon-only, 28×28). Screenshots `slice1.1-footer-{system,light,dark}.png`.
3. **Thread column and composer share one measure.** `--content-gutter` (24 px, 16 px under
   1080 px) is used by `.thread-dock`, `.view-inner` and `.composer-dock`, all capped at
   `--content-max`. `Thread.jsx` now renders `.thread-dock > .thread`.
4. **e2e/manual data isolation.** `playwright.config.js` starts its own `fods serve` on 8901 with
   `RLA_DATA_DIR=<frontend>/.e2e-data/data`; `e2e/global-teardown.js` deletes the whole
   `.e2e-data` root; `.gitignore` covers `.e2e-data/`. After a run: `.e2e-data` absent,
   `stitch_aesthetic_markdown_reader/data` absent, `git status` clean under `data/`, run count
   89 (82 originals + 7 created by earlier manual checks — see Blockers).
5. **Removed/added tests.** Removed: `test_frontend_source_exposes_react_views_and_event_backed_runtime`.
   Added: `test_frontend_shell_is_a_module_entry_without_the_legacy_classic_script`,
   `test_frontend_source_avoids_csp_unsafe_and_remote_constructs`, plus the four backend tests in
   `8cd8af1`. New frontend test files: `src/test/copy.test.js`, `src/test/contrast.test.js`,
   `src/sidebar/Sidebar.test.jsx`. Legacy shell (`shell-core.js`, `styles.css`, `vendor/`) has a
   **zero-line** diff since `3081afb`. New devDependencies are exact pins; `vite` and
   `@vitejs/plugin-react` keep their baseline carets.
6. **Contrast tested from the tokens.** `src/test/contrast.test.js` parses `tokens.css`, computes
   WCAG relative luminance, and requires ≥ 4.5:1 for 16 text/surface pairs in both themes. It
   found one real failure: light `--queued #7a8285` on `--queued-weak #f0f2f2` = **3.49** →
   changed to `#646c6f` (**4.77**). Dark was already ≥ 4.72 for the same pair.
7. **1280 and 768 verified.** Playwright asserts zero horizontal overflow on `documentElement`
   and `body` at both widths and a 64 px icon-only sidebar at 768 px. Screenshot
   `slice1.1-empty-768-collapsed.png`; measured `overflow {root: 0, body: 0}`, `sidebar768: 64`.
8. **`N` shortcut guarded.** It is ignored when the event target is `INPUT`, `TEXTAREA`, or
   `isContentEditable`, and when `ctrlKey`, `metaKey` or `altKey` is held. Tested in
   `App.test.jsx` (negative cases first, then a positive `N` on `body`).
9. **Recents are distinguishable.** Each row carries a relative time (`relativeTime`, with a
   `<time datetime>` for the absolute value), a status dot (`statusTone`), the short id, and a
   `Replay` badge when `mode === "replay"`. Backed by `started_at`/`ended_at` from
   `/api/history` (commit `8cd8af1`). Tested in `Sidebar.test.jsx`.
10. **CSP assertion replaced.** The `[style]` count is gone. The e2e spec records
    `securitypolicyviolation` events and console errors and requires both to be empty; CSSOM
    writes and SVG presentation attributes are therefore allowed. `setAttribute("style", …)` is
    still banned (the structural test in `tests/test_fods_frontend.py` greps for it).

**Slice 1.1 gate (measured):** pytest `813 passed, 1 skipped in 226.49s`; `ruff check src/ tests/`
all checks passed; vite build 1602 modules, 0.97 kB html / 20.34 kB css / 260.89 kB js; vitest
**83 passed in 9 files**; Playwright **4 passed**, `consoleErrors: []`, `cspViolations: []`.

**Backend commit `8cd8af1`** (needed by slices 2 and 4, not part of the UI gate): `/api/config`
now returns `limits` (the `NewRun` bounds) and `capabilities` (`ollama_planner`, `gemini`,
`gemini_opted_in`, `rla_live`); `llm_request_budget` defaults to `None` → the configured
`llm_daily_budget`, and a value above it is rejected with `code=budget_override_required` and a
field error unless `allow_budget_override` is set; history rows carry `started_at`/`ended_at`.
`tests/test_fods_webapp.py`: 14 passed.

## Slice 2 detail (composer `+` menu)

**Files.** `src/composer/model.js` (pure rules, no React), `src/composer/ComposerMenu.jsx` (the
popover), rewritten `src/composer/Composer.jsx`, `composer` slice in `src/store/reducer.js`,
`--z-popover` + popover/field/config styles.

1. **The menu has the four sections the owner specified**, in order: *Execution mode* (Live /
   Deterministic demo with a one-line description each), *Agent configuration* (read-only
   planner/structured/answer/embedding model ids, enabled sources, daily cap — all from
   `/api/config`), *Topic label* (optional; blank derives the label from the question and shows
   the derived value as the placeholder), *Advanced* (collapsed by default).
2. **No known-to-fail default path.** `defaultMode(config)` returns `demo` unless
   `capabilities.rla_live` is true, so the first send is a run that works. `liveBlocker(config)`
   returns the actual cause: *"Live runs need an Ollama planner. This runtime is configured for
   gemini/gemini-2.5-flash."* or *"Live runs need GEMINI_API_KEY, and this runtime does not have
   one."* Choosing Live anyway disables send (title repeats the reason), shows a warn-tone inline
   note, and offers **Run as deterministic demo** in one click.
3. **A-06 is structural, not a hint.** Untouched advanced fields are **omitted** from the POST, so
   the runtime default applies unchanged; only edited fields are sent. `allow_budget_override` is
   sent only when a value above the configured cap is explicitly ticked, and the checkbox text
   names the cap (`Allow 40 requests for this run, above the configured cap of 15`). The server
   already rejects an over-cap request with `code=budget_override_required` and a field error.
4. **Displayed defaults equal what the runtime will use if the field is omitted**, each labelled
   with its source: budget *15 · from /api/config*, everything else *20 / 300 / 3 / 3 · runtime
   default*. This is the UI-04 requirement — the old accordion showed a hardcoded 100.
5. **Validation is local *and* server-mapped.** Local validation mirrors `NewRun` bounds and runs
   on every keystroke, so `0` budget blocks submit with a visible message and **no POST**. A 400
   whose `fields` names an input renders the message next to that input *and* repeats it in the
   alert as `field: message`, so a field inside the closed menu is never silently dropped.
6. **Bounds cannot drift silently.** `tests/test_fods_composer_bounds.py` parses the JS `LIMITS`
   table and compares all 16 bounds to `fods.webapp.NewRun`'s pydantic metadata, and asserts the
   set of keys is exactly the mapped set. At runtime the UI still prefers `/api/config.limits`.
7. **Keyboard and focus.** Opens with focus on the checked mode; `Tab`/`Shift+Tab` cycle inside;
   `Escape` closes and returns focus to `+`; `Ctrl/Cmd+.` toggles from anywhere; a pointer down
   outside closes. `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls` on the trigger, and
   `role="dialog"` with a label.
8. **Layout.** The popover is 420 px wide capped at `100vw − 3 gutters`, `max-height: min(70vh,
   620px)` and scrolls; expanding Advanced scrolls the fields into view (found missing in the
   first 1280 capture). Zero horizontal overflow measured with the menu open at 1280 and 768.

**Slice 2 gate (measured):** pytest `817 passed, 1 skipped in 202.82s` (was 813+1; +4 bounds
tests); `ruff check src/ tests/` all checks passed; vite build 1602 modules, 0.97 kB html /
**24.15 kB** css / **275.99 kB** js; vitest **112 passed in 11 files** (was 83 in 9; +11 composer
component tests, +10 model tests, +3 reducer tests, and App tests updated for the new default
mode); Playwright **5 passed (3.2s)**. Screenshot run: `consoleErrors: []`,
`cspViolations: []`, `overflow {root:0, body:0}` at 1280 and 768, also with the menu open.

**Evidence:** `docs/audit/screenshots/slice2-menu-{1280,768}.png`,
`slice2-menu-advanced-1280.png`, `slice2-menu-advanced-light-1280.png`; the four slice-1.1
screenshots were regenerated because the composer gained the `+` trigger.

## Slice 3a detail (backend for the UI)

**Files.** New `src/fods/event_meta.py`; `src/fods/events.py`; `src/fods/runtime.py`;
`src/fods/cli.py`; `src/fods/webapp.py`; new `tests/test_fods_event_meta.py`; additions to
`tests/test_fods_runtime.py` and `tests/test_fods_webapp.py`.

1. **One derivation, written at emit time.** `event_meta.describe(kind, message, payload)`
   returns `summary`, `phase`, `event_class`, `severity`, `duration_ms`. `EventLog.emit()`
   calls it, so every new event is displayable from the record alone. `RuntimeEvent` keeps the
   attribute `event_class` because `class` is a Python keyword; `to_dict()` writes the wire key
   **`class`** and never `event_class`. The module is named `event_meta`, not `enrichment`,
   because the repo already has paper-concept "enrichment" (`tests/test_fods_enrichment.py`,
   tool `extract_enrichment_batch`).
2. **Phase comes from the record, never from `kind` alone.** RLA uses `payload.phase`; FODS
   derives it from the task's tool (`search_*`/`acquisition_checkpoint` → acquire,
   `merge_and_save_context` → merge, `retrieve_evidence` → evidence, `draft_cited_answer` →
   answer, `validate_citations` → validate, `write_cited_brief` → write), with plan/queue/
   runtime bookkeeping classes. Summaries are one line, ≤90 chars, no raw JSON; counts are
   taken from the payload (`plan validated — 8 tasks, 6 levels`).
3. **Terminal-event guarantee (A-01).** `_guarantees_terminal_event` wraps `run_plan` and, in
   `finally`, emits exactly one `run_finished` only if the body did not. Today the only gap was
   `plan_rejected`; a normal run still emits its own single terminal event. Two tests pin both
   directions (rejected plan → one `run_finished` with `termination_reason=plan_rejected`;
   completed run → exactly one).
4. **Authoritative run info (UI-08, A-01, A-04).** `GET /api/runs/<id>` now returns
   `status`, `status_reason` (the recorded `termination_reason`), `started_at`, `ended_at`,
   `elapsed_ms` (recorded, else derived from the two timestamps), `pipeline`, and
   `unavailable_sources`. `handle.status` is preserved, so a replayed run still reports
   `replayed` while `status_reason` says why the original run ended.
5. **Status without polling (UI-08).** The SSE envelope carries `status` and `status_reason`.
   The handle's own status is set *after* the terminal event is published, so the terminal
   envelope derives its status from the recorded `run_finished` instead of echoing a stale
   `starting`; replays report `replayed`.
6. **RLA durations and failures (UI-11, A-04).** `run_started` carries
   `pipeline="rla-phases"` and `pipeline_stages` (the ten `PIPELINE_PHASES` with labels and
   order); `run_finished` carries the real `elapsed_ms`, `failed_sources` names and
   `stages: [{id, started_ms, duration_ms}]` computed from the recorded progress events. A
   phase with no progress event is absent, never shown as zero. FODS `run_started` carries
   `engine="fods"`, `pipeline="fods-scheduler"`.
7. **Brief machine-readable + download (UI-09).** `GET /api/runs/<id>/brief` is unchanged
   Markdown; `?format=json` returns `{run_id, markdown, citations, sources}` (sources read
   from the recorded `context_ready`/`research_papers`); `?download=1` adds
   `Content-Disposition: attachment; filename="<run_id>.md"`. A missing brief is
   `404 {code: "brief_not_found"}` (slice 3b; 3a used the generic `not_found`).
8. **Stable error codes (A-12 groundwork).** POST errors now carry `code`: `validation`
   (pydantic, with `fields`), `budget_override_required` (with `fields`), `invalid_request`,
   `conflict`, `not_found`.

**Slice 3a gate (measured, this worktree):** pytest `838 passed, 1 skipped in 255.27s` (was
817+1; +21: 11 event-meta, 2 terminal-guarantee, 8 webapp); `ruff check src/ tests/` all checks
passed; vite build unchanged at 24.15 kB css / 275.99 kB js (no frontend source touched);
vitest `112 passed in 11 files`; Playwright `5 passed (5.1s)`. Screenshot run not repeated: the
bundle hash is identical to slice 2. `data/` untouched (89 runs, `git status` clean).

**Parity evidence.** All three golden fixtures describe cleanly (114 / 55 / 381 events), and
all **89 real logs (10,439 events)** produce a non-empty summary ≤90 chars with no path-like
text. Replaying `17ee03228c0b` through `RunManager` gives **114/114 byte-identical events**, no
invented `summary`/`phase`/`class` on old records, `status="replayed"`,
`status_reason="completed"`, `elapsed_ms` derived from the recorded timestamps.

**Not verified here.** Docker on 8765 is not running on this machine, so the container's old
UI was not re-checked; slice 9 rebuilds it. `src/fods/web/` is untouched and its `dist/` is
gitignored.

## Slice 3b detail (backend hardening)

**Files.** `src/fods/safety.py`; `src/fods/events.py`; `src/fods/webapp.py`; new
`tests/test_fods_safety.py`; additions to `tests/test_fods_webapp.py`.

1. **A-02 — a run outlives the process.** `GET /api/runs/<id>` and
   `GET /api/runs/<id>/events` no longer require a live handle. When the handle is absent (a
   restart, or an evicted run) both are served from `data/fods/runs/<id>.jsonl`:
   - the info response is marked `"historical": true`;
   - the SSE replay is the recorded log, every envelope carrying `"historical": true` and the
     final `status`/`status_reason`; it starts with `retry: 3000` so EventSource reconnects if
     the connection drops, and it sends `Connection: close` because a replay is finite;
   - `Last-Event-ID` still works on the disk path.
   A run the memory ring has evicted stays readable from disk.
2. **A-02 — bounded memory.** `MAX_FINISHED_HANDLES = 24`. `_evict_finished()` drops the oldest
   finished handles (and their idempotency keys) before each `start()`/`replay()`; running
   handles are never evicted. The disk is the retention policy, not the process.
3. **A-09 — one corrupt line hides nothing.** `read_events(path, strict=False)` returns
   `(events, skipped)`; `EventLog`/CLI call sites keep the strict default. `RunManager.history()`
   and the disk paths use the tolerant form, so a half-written line costs that line, not the
   run: the row appears with `warnings: <n>` and, with no readable `run_finished`, status
   `interrupted`. History rows are cached by `(st_mtime_ns, st_size)` and reparsed only when the
   file changes; entries for deleted files are dropped.
4. **A-07 — the validation flag follows the check.** `_brief_saved_payload()` sets
   `citations_validated = not stripped_citations` and records `stripped_citations`. A run that
   had an unsupported citation id no longer emits a "validated" claim.
5. **A-08 — brief failure modes.** A brief over `MAX_BRIEF_BYTES` (2 MiB) is
   `413 {code: "brief_too_large"}`; a brief that cannot be resolved because the log is corrupt is
   `500 {code: "brief_unreadable"}`; a missing brief is `404 {code: "brief_not_found"}`.
   `?format=json` skips credential redaction (so Markdown is not mangled) but is still
   path-sanitised.
6. **A-11 — no absolute paths, no foreign writes.** `safety.relative_path()` /
   `sanitise_paths()` rewrite `C:\…` and `/Users|/home|…` paths to workspace-relative ones
   (`…/basename` when the root is unknown). They run at **emit** time
   (`EventLog(roots=…)`, used by the webapp) and again at the **serve** layer (JSON, SSE, history,
   disk replay), so records written before this rule are scrubbed on the way out. `do_POST` and
   `do_DELETE` now require a loopback `Host` and either no `Origin` or this server's own origin
   (plus `RLA_FODS_DEV_ORIGIN` for the Vite dev server); rejection drains the body first so the
   client actually receives the 403. Codes: `forbidden_host`, `forbidden_origin`.
7. **A-12 — codes on delete/history paths.** `run_not_found`, `run_finished`,
   `cancellation_requested`, `log_unreadable`, `brief_not_found`, `brief_too_large`,
   `brief_unreadable`.

**Slice 3b gate (measured, this worktree):** pytest `855 passed, 1 skipped in 294.84s` (was
838+1; +17: 6 safety, 11 webapp); `ruff check src/ tests/` all checks passed; vite build
unchanged at 24.15 kB css / 275.99 kB js (no frontend source touched); vitest
`112 passed in 11 files`; Playwright `5 passed (7.9s)`; `data/` untouched (`git status` clean).

**Slice 3b parity (read-only, against the stored corpus).** 69 hex-named logs plus 20 benchmark
logs: strict and tolerant readers agree on every hex log (0 skipped lines, 0 strict failures);
history returns 69 rows with 0 warnings and no absolute path in the serialised output.
`efee736eb669` (the known A-11 record) has **7** absolute paths in the raw events and **0** after
sanitising; its stored brief path is served as `data/fods/briefs/efee736eb669.md`. The single
`interrupted` row is `8c5a5ba36606`, the pre-3a `plan_rejected` run that genuinely has no
`run_finished`; before this slice it was reported as `unknown`.

**Not verified here.** The Docker image on 8765 was not running, so the container path is
NOT VERIFIED for 3b too. No browser was used to exercise the new `retry:`/`historical` fields;
that wiring lands in slice 4.

## Slice 4 detail (thread lifecycle, Stop)

**Files.** `src/fods/webapp.py`; frontend `lib/events.js`, `store/reducer.js`,
`store/selectors.js`, `store/useRunStream.js`, new `composer/useStopRun.js`, `composer/Composer.jsx`,
`app/App.jsx`, `thread/Turn.jsx`, `thread/Thread.jsx`, `styles/app.css`; tests
`tests/test_fods_webapp.py`, `lib/events.test.js`, `store/reducer.test.js`, new
`thread/Turn.test.jsx`, `app/App.test.jsx`, `views/views.test.jsx`, `e2e/studio.spec.js`.

1. **A-10 — Stop is real for both engines.** `DELETE /api/runs/<id>` already set
   `handle.cancel_event`, and the FODS runtime checks it every scheduling iteration
   (`runtime.py:685`, `876`). The RLA wrapper did not take it at all, so a DELETE on an RLA run
   was a false confirmation. `_execute_research_pipeline` now checks `handle.cancel_event`
   between pipeline items, stops requesting work, emits
   `run_finished(termination_reason="cancelled", cancellation_requested=True)` and calls
   `handle.finish("cancelled", "stopped on request")`. The shared `src/rla` pipeline is not
   modified. `_status_from_finish` checks `cancelled` **before** `succeeded`, so a Stop that
   lands as the last item completes is reported as stopped, not completed.
2. **One derivation for the in-thread list.** `workingLines(events)` returns the last six
   non-terminal one-liners, each phase-tagged by the recorded `payload.phase`, plus `more`;
   `workedFor(events)` reads `elapsed_ms` and `stages` from the terminal record only, and
   `answerFrom(events)` reads `research_answer`/`answer_ready`. The list lives in one
   `aria-live="polite"` region and is throttled in `Turn` to one update per 500 ms (a 114-event
   demo cannot flood a screen reader). On the terminal event the list is removed and replaced by
   `Worked for 2m 14s · 9 steps`; when `elapsed_ms` is absent the button says "Worked for an
   unrecorded duration", never a guess. The button's accessible name still contains
   "open execution trace", so both the existing selector and the design's "expandable into the
   Trace" intent hold.
3. **Status is derived, then reconciled.** `useRunStream` fetches `GET /api/runs/<id>` on mount,
   on selection (the effect re-runs) and on every `onState("live")` (reconnect) and dispatches
   `run/info`. The reducer refuses to let the fetch walk a status backwards after events have
   arrived and refuses to overwrite a terminal event already in the stream. `Stopping` is a UI
   state, not a backend status: it shows on the chip only after the DELETE was sent, is cleared
   by `run/stop-rejected` or by any recorded terminal event, and is replaced by `Stopped` when
   the record says `cancelled`.
4. **New investigation is honest about the old run.** It requests cancellation of a live,
   non-replay run before clearing, then bumps `composerEpoch` (the question text lives in the
   Composer, not the store, so a store-only reset cannot clear it), resets topic/advanced/budget
   overrides, and keeps the chosen mode. If the stop request fails the conversation stays
   visible and the banner says why. Stop is **hidden** — not disabled-with-a-lie — for a replay
   and for a run read from disk, where there is no live process to cancel.
5. **A-07 in the thread.** An answer whose citations could not be matched to the evidence graph
   gets an explicit "N citations ... were removed" note; the answer is never labelled validated.
   `warnings > 0` from the tolerant log reader is also stated ("N unreadable log lines were
   skipped").

**Slice 4 gate (measured, this worktree):** pytest `858 passed, 1 skipped in 211.59s` (was
855+1; +3 webapp: cancelled-before-succeeded, demo Stop, RLA cancel between items);
`ruff check src/ tests/` all checks passed; vite build 25.19 kB css / 282.59 kB js (was
24.15/275.99); vitest `137 passed in 12 files` (was 112; +25: events, reducer, new Turn tests,
App lifecycle, views); Playwright `7 passed (9.3s)` (was 5; +worked-for collapse + Stop);
`data/` untouched (`git status` clean) and `src/fods/web/` unchanged.

**Not verified here.** A live RLA Stop was exercised with a fake pipeline (no `GEMINI_API_KEY`
on this machine); the real provider path is NOT VERIFIED until a key is present. Docker on 8765
still serves the old UI (slice 9).

## Blockers / notes

- `dist/` is **not** tracked and is gitignored (`.gitignore:18`); the build output is produced by
  `npm run build` and by the Docker multi-stage build. No `dist/` is committed anywhere.
- `data/fods/` is gitignored (`.gitignore:10`), so the 82 logs copied in for local serving can
  never be committed.
- `.env` is gitignored (`.gitignore:22`).
- **Seven runs created by manual slice-1/1.1 checks sit in `data/fods/runs/`** (89 total = 82
  originals + 7). All are 114-event deterministic demos; briefs exist for six. Owning them is the
  owner's call, so they are listed in the review note and **not deleted**. The 82 original logs are
  never touched. After slice 1.1 the e2e/screenshot path uses a throwaway `RLA_DATA_DIR`, so a
  normal gate run adds nothing.
- The Docker container on 8765 still serves the **old** UI. Slice 9 rebuilds it; until then the
  new shell is only on `fods serve` from this worktree. For slice 9's dev loop, `FODS_API_PORT`
  selects the Vite proxy target (`8765` is the container; e2e/screenshots use `8901`).
