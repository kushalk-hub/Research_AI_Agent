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
| 4 | RLA cooperative cancel, minimal diff; stop and ask if invasive | planned (slice 4) |
| 5 | Budget = configured cap verbatim + explicit override, enforced server-side with `fields` + stable `code`; remove `webapp.py:57` default of 100 | **done** (`8cd8af1` + slice 2; server returns `code=budget_override_required`, composer states the cap and needs a tick) |
| 6 | Backend one-liners + single `describeEvent()` fallback; redacted, ≤90 chars, no raw JSON/paths | planned (slice 3a + 7) |
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
| 3a | Backend for UI: enrichment, `pipeline`, status, terminal guarantee, brief JSON, codes | planned | — | |
| 3b | Backend hardening: A-02, A-03, A-07, A-08, A-09, A-11 | planned | — | |
| 4 | Thread lifecycle: working lines, chip, New investigation, Stop | planned | — | |
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
