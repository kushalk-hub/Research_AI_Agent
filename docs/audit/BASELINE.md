# BASELINE — measured before any change

**Date:** 2026-11-15
**Branch:** `feature/studio-redesign` (new) · **Base:** `codex/research-frontend-5paper-checkpoint`
**Base commit:** `3081afb12708b9406d192bec6711d05d13c2d2e6` — confirmed, as the audit assumed.
**Worktree:** `D:\fods-studio-redesign` (the `main` worktree and its staged/untracked files were not
touched).

Everything below was executed in this worktree. Nothing is copied from the docs.

---

## 1. Environment

| Item | Value |
|---|---|
| Python | 3.12.8 (`py -3.12`), venv at `D:\fods-studio-redesign\.venv` |
| Install | `.venv\Scripts\python -m pip install -e ".[dev,tui]"` → success |
| `fods.__file__` | `D:\fods-studio-redesign\src\fods\__init__.py` (inside the worktree, verified) |
| `rla.__file__` | `D:\fods-studio-redesign\src\rla\__init__.py` |
| Node / npm | v26.13.0 / 11.20.0 |
| Docker | `Docker version 29.9.2, build a82e528` (client + engine present) |
| `.env` | copied from `.env.example` (blank `GEMINI_API_KEY`); gitignored |

Resolved versions of note (the ranges in `pyproject.toml` are open, so the environment is
**newer than the one the docs describe**): pytest 9.2.0, ruff 0.17.5, pydantic 2.14.3,
httpx 0.28.1, google-genai 3.3.0, textual 8.2.8, respx 0.23.1, networkx 3.7.
No failure below is attributable to this drift; it is recorded because a pinned lockfile would
make future runs reproducible.

---

## 2. Backend

### Tests

```
.venv\Scripts\python -m pytest tests/ --collect-only -q
809 tests collected in 3.16s

.venv\Scripts\python -m pytest tests/ -q
808 passed, 1 skipped in 139.85s (0:02:19)
```

**Zero pre-existing failures.** Nothing to classify.

### Test-count reconciliation (A-14)

| Claim | Source | Measured | Verdict |
|---|---|---|---|
| 668 | `README.md:499` | — | **stale / wrong** |
| 742 | static `def test_` count at `3081afb` | — | static count only; parametrisation expands it to 809 |
| 808 + 1 skipped | `docs/master.md:37,65` | 808 passed, 1 skipped | **correct** |

So: **809 collected = 808 passed + 1 skipped**, and `docs/master.md` is accurate while
`README.md` is not. `README.md:499` will be corrected in slice 9 (docs slice) to state the
measured number with command, date and commit.

### Lint

```
.venv\Scripts\python -m ruff check src/
All checks passed!
```
(ruff 0.17.5; `pyproject.toml` selects `E,F,I,UP,B`, line-length 100.)

### Serve + deterministic demo

Port 8765 is **already occupied** on this machine: pid 15132 `com.docker.backend` answers
`/api/health` with `{"ok": true}` and `/api/config` with a real config
(`gemini_key_configured: true`, `paper_limit: 20`, `llm_request_budget: 15`,
`modes: ["live","simulate","replay"]`) — i.e. a **containerised instance of this app is running**.
It is not my process; I did not touch it, and I did not read its `.env`. My baseline used 8877.

```
.venv\Scripts\python -m fods.cli serve --host 127.0.0.1 --port 8877
GET /api/health           -> {"ok": true}
GET /                    -> 200 text/html; charset=utf-8, 845 bytes (built dist/index.html)
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self';
  connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'
POST /api/runs            -> simulate / engine=fods / planner=fixture
  run_id b193eefa1ad7, status "starting", event_count 0, events_url present
GET /api/runs/b193eefa1ad7  (after ~6 s)
  {"status":"completed","event_count":114,...}
GET /api/runs/b193eefa1ad7/brief
  200, text/markdown; charset=utf-8, 1343 bytes, Content-Disposition: (none)
GET /api/history
  63 runs, newest b193eefa1ad7 completed 114
```

The simulate demo reproduces the recorded `17ee03228c0b` log exactly (114 events).

---

## 3. Frontend

```
cd stitch_aesthetic_markdown_reader
npm ci        -> added 66 packages, 0 vulnerabilities
npm run build -> vite v6.4.6, 1578 modules transformed
                 dist/index.html                 0.86 kB │ gzip: 0.51 kB
                 dist/assets/index-C4ZCwE29.css 23.34 kB │ gzip: 5.90 kB
                 dist/assets/index-dYS1PXQI.js 269.44 kB │ gzip: 82.13 kB
                 ✓ built in 1.30s
```

Two build observations, both pre-existing:

1. `vite` warns: `<script src="/shell-core.js"> in "/index.html" can't be bundled without
   type="module"`. The legacy shell core is loaded as a classic script and is therefore **not**
   bundled — it is served as a separate file by `webapp.py:675-676`.
2. `npm ci` warns that `esbuild@0.25.12` has a postinstall script not covered by `allowScripts`
   (npm 11 policy). The build still works.

`npm test` does not exist yet (`package.json` has `dev`, `build`, `preview` only) — so there is
no frontend test baseline. This is the gap that UI-05's "covered by an automated UI test" hits;
slice 1 adds `vitest` + Testing Library + jsdom.

`dist/` is **not tracked**: `.gitignore:18` ignores `dist/`, and
`git ls-tree ... -- src/fods/web/dist` is empty at `3081afb`. The build output is produced by
`npm run build` and by the Docker stage. **No `dist/` will be committed** (answer to Gate A
decision 7's `git ls-files` question).

---

## 4. Citation spot-check (audit was written from a `git archive` export)

Re-read in the real worktree at `3081afb`. **Zero drift** — all seven citations are exact:

| Citation | Expected | Found |
|---|---|---|
| `main.jsx:143` | "New investigation" only calls `setPage("research")` | `onClick={() => setPage("research")}` ✓ |
| `main.jsx:210` | budget floored at 100 | `setBudget(Math.max(100, config.llm_request_budget \|\| 100));` ✓ |
| `webapp.py:91` | status starts `"starting"` | `status: str = "starting"` ✓ |
| `webapp.py:428` | hardcoded `citations_validated=True` | `citations_validated=True,` ✓ |
| `webapp.py:447` | RLA duration not recorded | `elapsed_ms=None,` ✓ |
| `runtime.py:226-227` | `plan_rejected` then re-raise | `log.emit("plan_rejected", …)` / `raise` ✓ |
| `shell-core.js:15-18` | Lab keys off `plan_validated`/`plan_received` | the reverse-`find` + `payload.tasks` lines ✓ |

Two audit questions resolved from the code, both recorded in PROGRESS.md:

- **`abstained` (decision A):** no abstention flag exists anywhere in `src/`. The only trace is a
  prompt instruction, `tools.py:298` — *"If the evidence is insufficient, say so."* So there is
  nothing to display as a badge; `abstained` will be removed from the UI status enum and docs.
- **`?after=` (decision E):** already supported — `webapp.py:745` reads
  `Last-Event-ID` and falls back to the `after` query parameter. No server change needed.

---

## 5. Fixtures copied for tests

Verbatim copies of first-party evidence, committed so tests do not depend on gitignored `data/`:

| File | Events | Why |
|---|---|---|
| `tests/fixtures/fods_logs/efee736eb669.jsonl` | 55 | RLA run: `pipeline: rla-phases`, 50 progress events, real `stage_payload` counts |
| `tests/fixtures/fods_logs/17ee03228c0b.jsonl` | 114 | deterministic simulate: 8 tasks, 6 levels, full scheduler vocabulary |
| `tests/fixtures/fods_logs/Q01-deep.jsonl` | 381 | live deep run: 26 tasks, 8 levels, the performance target |

They are **not** scrubbed: they contain `D:\Research_AI_Agent-fods\...` absolute paths, which is
exactly what the serve-layer redaction test (decision B) must catch. The originals in `data/` are
never rewritten.

---

## 6. New observations (pre-existing, not in the audit)

Recorded, not fixed — none of them changes scope, but they are honest findings:

1. **`/api/history` hides 20 of the 82 logs.** `history()` iterates `runs_dir/*.jsonl` and the
   `Q01-deep`-style filenames fail the `^[0-9a-f]{12}$` `RUN_ID` pattern, so the 20 `Q01..Q10`
   deep/quick benchmark runs never appear in the Library and cannot be replayed. 82 logs − 20 =
   62, + the new run = 63, which is exactly what `/api/history` returned. (Minor; out of audit
   scope. Will be noted in the submission report.)
2. **SSE does not signal end-of-stream to a client that waits for EOF.** The handler writes all
   events and returns (`webapp.py:779-780`), but the response keeps
   `Connection: keep-alive` with no `Connection: close`, so `Invoke-WebRequest` on a *finished*
   run hangs until the client times out (observed at 90 s). Browsers' `EventSource` is unaffected
   because it reconnects. The new UI must close on the terminal event, which is the design's plan.
3. **`ConnectionResetError` tracebacks in the server console** when a client disconnects mid-
   request (`socketserver` prints the traceback from `handle_one_request`). Cosmetic, pre-existing.
4. **`GET /` serves the built `dist/` when present, else the legacy `index.html`**
   (`webapp.py:653-657`). Slice 9 must replace that fallback with a clear instruction rather than
   silently serving the dead shell.
