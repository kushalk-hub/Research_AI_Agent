# PROGRESS — studio redesign

**Branch:** `feature/studio-redesign` · **Base:** `codex/research-frontend-5paper-checkpoint` @
`3081afb` · **Worktree:** `D:\fods-studio-redesign` · Gate A approved 2026-11-15 (with amendments).

This file is the durable memory of the work. Update after every slice.

## Decisions in force (from Gate A approval)

| # | Decision | State |
|---|---|---|
| 1 | Separate worktree + new branch; own venv; `main` staging untouched | done (`D:\fods-studio-redesign`, venv at `.venv`) |
| 2 | UI-07 = option (a) labelled phase graph + "Run the deterministic demo" chip in the empty thread | planned (slice 8 + slice 1) |
| 3 | `vitest`, `@testing-library/react`, `jsdom` pinned; Playwright dev-only via `npm run test:e2e`, never in Docker | planned (slice 1) |
| 4 | RLA cooperative cancel, minimal diff; stop and ask if invasive | planned (slice 4) |
| 5 | Budget = configured cap verbatim + explicit override, enforced server-side with `fields` + stable `code`; remove `webapp.py:57` default of 100 | planned (slice 2 + 3a) |
| 6 | Backend one-liners + single `describeEvent()` fallback; redacted, ≤90 chars, no raw JSON/paths | planned (slice 3a + 7) |
| 7 | Delete legacy shell only in slice 9, after green behavioural tests; keep `tests/fixtures/fods_frontend/demo_data.json` | planned (slice 9) |
| 8 | Copy Docker files; add `RLA_FODS_ALLOW_GEMINI`; run real build or write NOT VERIFIED | planned (slice 9) |
| A | `abstained`: no new abstention logic; remove from enum/docs unless the answer stage already exposes a flag | to check |
| B | Path leaks: relativise on emit **and** sanitise at the serve layer; old logs replay with identical semantics, only redaction differs; scan test over a fixture copy | planned (slice 3b) |
| C | §6 backend list extended with A-02, A-03, A-07, A-08, A-09, A-11 | planned (slice 3b) |
| D | A-01 `finally` in `runtime.py` approved; no queue/ordering change; update `test_fods_runtime.py` deliberately | planned (slice 3a) |
| E | Server `?after=<lastSeq>`: add additively if absent | to check (slice 3a) |
| F | Markdown renderer: React text nodes only, `http(s)` links only, XSS tests | planned (slice 6) |
| G | "24 tasks" → 26 in design doc examples | **done** (before approval) |

## Slices

| # | Slice | Status | Commit | Gate |
|---|---|---|---|---|
| 0 | Step 1: worktree, baseline, citation spot-check, fixtures | **done** — see `BASELINE.md` | Step 1 commit | pytest 808 passed / 1 skipped · ruff clean · build green |
| 1 | Foundation: tokens, theme, shell (sidebar/thread/composer), store, SSE manager | planned | — | **STOP for review** |
| 2 | Composer `+` menu, mode, config, advanced validation, budget | planned | — | |
| 3a | Backend for UI: enrichment, `pipeline`, status, terminal guarantee, brief JSON, codes | planned | — | |
| 3b | Backend hardening: A-02, A-03, A-07, A-08, A-09, A-11 | planned | — | |
| 4 | Thread lifecycle: working lines, chip, New investigation, Stop | planned | — | |
| 5 | Answer + evidence: citation chips, scroll, `[C#]` | planned | — | |
| 6 | Brief overlay | planned | — | |
| 7 | Trace: waterfall, filters, detail, virtualisation, in-chat lines | planned | — | |
| 8 | Lab: DAG, queue, workers, stacks, playback, RLA phase rail | planned | — | **STOP for review** |
| 9 | Cleanup, a11y, docs, screenshots, Docker | planned | — | |

## Blockers / notes

- `dist/` is **not** tracked and is gitignored (`.gitignore:18`); the build output is produced by
  `npm run build` and by the Docker multi-stage build. No `dist/` is committed anywhere.
- `data/fods/` is gitignored (`.gitignore:10`), so the 82 logs copied in for local serving can
  never be committed.
- `.env` is gitignored (`.gitignore:22`).
