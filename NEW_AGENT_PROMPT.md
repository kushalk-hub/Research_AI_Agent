# NEW_AGENT_PROMPT.md — paste this into the replacement coding agent

> Owner: before pasting, set the line marked **OWNER STATUS** in section 1.
> Put nothing else in the first message; the agent reads the repo for context.

---

You are taking over the FODS Research Studio rebuild from a previous coding agent that hit a rate
limit. You are a different agent. **Trust the repository over anyone's memory, including the
handoff notes: verify before relying on them.** Your job is to finish the project: slice 9, then
the final submission check (Gate B).

## 1. Status you are given

- Branch: `feature/studio-redesign` (base `codex/research-frontend-5paper-checkpoint` @ `3081afb`).
- Done and committed: Step 1, slices 1, 1.1, backend, 2, 3a, 3b, 4, 5, 6, 7, **8 (FODS Lab)**.
- Remaining: **slice 9**, then Gate B (fresh-clone verification, `docs/SUBMISSION_REPORT.md`).
- Last measured baseline (from the previous agent, **re-measure it yourself**): pytest 859 passed
  / 1 skipped; ruff clean; build 55.70 kB css / 349.76 kB js; vitest 242 passed; Playwright 11
  passed.
- **OWNER STATUS:** slice 8 reviewed by the owner: `[ YES — approved / NO — not yet ]`
  *(If NO, or if this line is not filled in, do the read-only steps in section 2, then **stop and
  ask**. Slice 9 deletes the legacy UI, so it must not start before the owner has reviewed the
  Lab.)*

## 2. Resume protocol (read-only; no edits until step 5 passes)

1. Read, in this order: `AGENTS.md`, `docs/agent_handoff/README.md`,
   `docs/agent_handoff/CURRENT_STATE.md`, `docs/agent_handoff/SETUP_AND_COMMANDS.md`,
   `docs/audit/PROGRESS.md`, `docs/FRONTEND_DESIGN.md`. Read `docs/audit/AUDIT_FINDINGS.md`
   **by section** as needed (it is ~1,400 lines; do not load it whole every time). If present,
   also read `Project_changes.md`, `AGENT_PROMPT.md`, `GATE_A_APPROVAL.md`.
2. Verify the repo: `git branch --show-current` is `feature/studio-redesign`; `git status` is
   clean; `git log --oneline -15` shows the slice commits (find slice 8 with
   `git log --grep "slice 8"`). If anything differs from this prompt, report it and stop.
3. Environment (PowerShell, Windows). Use the venv's tools, never PATH tools:
   `.\.venv\Scripts\python.exe`. Needed: git, Python 3.12, Node, npm. Playwright Chromium via
   `npx playwright install chromium`. **Docker** is required to finish slice 9; if unavailable,
   the Docker items are reported as **NOT VERIFIED**, never assumed. Ollama is only needed for
   live FODS runs; the test suite must not depend on it. `.env` must exist and must never be
   committed or printed.
4. Re-measure the baseline: pytest, `ruff check src/ tests/`, `npm run build`, `npm test`,
   `npm run test:e2e`. Compare with section 1. Classify any difference as new or pre-existing
   and report it; do not fix unrelated failures silently.
5. Post a 5-line status (state, baseline numbers, anything unexpected). Then continue, unless
   OWNER STATUS is not YES.

## 3. Decisions already made (do not re-ask)

Cooperative RLA cancel was approved; configured budget cap (15) with explicit override;
backend one-liner `summary` plus one frontend `describeEvent()` fallback; no Markdown library
(React text nodes only); `abstained` removed from the UI/doc status enum unless the answer stage
exposes a real abstention flag; stored logs are never rewritten (path redaction happens at the
serve layer); Playwright is dev-only and never enters Docker; new dependencies must be
exact-pinned with a licence noted; delete the legacy shell only in slice 9.

## 4. The handoff's slice 9 list is incomplete. Do all of this

`docs/agent_handoff/NEXT_SLICE_9_PROMPT.md` is a good start but omits approved items. Slice 9 =
the union of that file and the following:

**A. Remove the legacy UI (approved decision 7).** Delete `src/fods/web/index.html`, `app.js`,
`shell.js`, `styles.css`, `vendor/d3-*`, and the server routes that serve them
(`/shell-core.js`, vendor routes). Check first that nothing in the new React app imports them.
Replace the old source-grep test and delete the d3-vendor test; the behavioural tests already
cover the replacement. Keep `tests/fixtures/fods_frontend/demo_data.json`. If `fods serve` finds
no built `dist/`, it must print a clear "run `npm run build`" instruction. Check
`git ls-files src/fods/web/dist` and follow the repo's existing convention; tell the owner what
you found. Record test counts before and after.

**B. Docker (approved decision 8).** Confirm `Dockerfile`, `compose.yaml`,
`requirements-docker.lock`, `.dockerignore` are **tracked on this branch** (copy them from `main`
if not; never move or alter `main`'s files). Add the `RLA_FODS_ALLOW_GEMINI` row to
`.env.example`. Run `docker build` and `docker run`, then
`curl.exe -s http://127.0.0.1:8765/api/health` must return `{"ok":true}` and the container must
serve the **new** UI. The existing container on 8765 serves the old UI: stop or replace it and
tell the owner. Playwright must not be in the image (check the image contents, not just the
Dockerfile). Run `npm run test:e2e` against the Docker-served build.

**C. Accessibility pass.** Keyboard operation for every interactive surface including the `+`
menu, trace rows, citation chips, brief drawer (focus trap and restore, Esc), Lab playback and
graph; visible focus rings; status never conveyed by colour alone; one `aria-live="polite"` region
for status; reduced-motion honoured (no auto-advance, durations ≈ 0); the SVG graph has the
state-table alternative; WCAG AA contrast in both themes (the contrast unit test from slice 1.1
must still pass and cover any new tokens). If an `axe` check can be added without a new
dependency, do it; otherwise state that axe was not run.

**D. Honesty and copy audit.** Search all UI copy for: prove, proof, verified, accurate,
guaranteed, "scheduler/queue/worker/parallel" on RLA screens. Every `partial` status must show
its reason. The RLA Lab banner must say sequential, not a task DAG. The standing note
"retrieval quality pending human review" must appear on the Library and the answer footer.

**E. Docs.**
- README: the headline command is wrong for a fresh clone; make every command match the working
  venv commands and **run each one as written**. Document `FODS_API_PORT`, the shell routes, and
  the Docker steps.
- **One measured test number**, in the README only, with command, date and commit; make
  `docs/master.md` reference it instead of repeating 668/797/808.
- Remove `abstained` from the docs; fix the "24 tasks" examples in `docs/FRONTEND_DESIGN.md`
  (real `Q01-deep` has 26).
- Keep the project's honest framing (retrieval quality PENDING HUMAN REVIEW; no accuracy claims).

**F. Screenshots.** Refresh at 1280 px and 768 px, light and dark: empty state, answer + evidence,
brief drawer, trace, Lab (FODS demo **and** RLA phase rail), Library. Save under
`docs/audit/screenshots/`. No horizontal page scroll at either width.

**G. Cleanup.** Remove the scratch files named in the handoff (`full_test.out`, `run.log`,
`results*.txt`, `test_out.txt`, `test_output.txt`, `test_p8_gap.out`) after confirming they are
scratch. Verify `.gitignore` still ignores `data/graph/`, `.env`, `.e2e-data/`, `dist/`. Remove
dead code and unused assets introduced during the rebuild.

## 5. Rules (non-negotiable)

- **Git safety.** The handoff's commit recipe uses `git add -A`. **Do not.** There are untracked
  demo runs and scratch files; stage explicit paths only, and run `git status` and
  `git diff --cached --stat` before every commit. Never commit `.env`, `node_modules`,
  `data/` run artifacts, `.e2e-data/`, or secrets. Commit messages as UTF-8 without BOM. No
  force-push. Work only on `feature/studio-redesign`; never commit to `main` or the `codex/...`
  branch.
- **Data.** Never touch the 82 original logs in `data/fods/runs/`. The 7 extra demo runs from
  slice 1/1.1 checks: **list them and ask the owner** before deleting. Do not regenerate
  `data/corpus.json`, `data/extractions.jsonl`, `data/concepts.json`.
- **CSP.** Test against the served build (`fods serve`, or the Docker image), not only Vite dev.
  Zero CSP violations and zero console errors. No `dangerouslySetInnerHTML`, no
  `setAttribute('style', …)`, no webfonts or CDN assets.
- **Evidence.** Never say fixed, passing, building or verified unless you ran it and saw the
  output. Paste the real summary lines. "NOT VERIFIED" is an acceptable answer; a guess is not.
- **Scope.** No new features. Backend changes only if a slice-9 bug requires one; say why. If you
  find a new problem or need a decision that changes scope, stop and ask.
- Per-slice gate: pytest, ruff, `npm run build`, `npm test`, `npm run test:e2e`; commit in small
  logical commits (A, B, C…) rather than one giant commit; post a 3-line status after each.
- If time runs short, cut in this order and say what you cut: (1) axe, (2) extra screenshot
  variants beyond 1280 px light and dark, (3) a11y polish beyond keyboard and focus. **Never cut:**
  legacy-UI removal with tests green, Docker verification (or an honest NOT VERIFIED), the copy
  audit, README commands that actually run, the single measured test number.

## 6. Gate B (after slice 9)

1. **Fresh clone check** in a new temp directory from the branch (not your working copy): create
   the venv, install, `npm ci`, build, `pytest`, `ruff`, `npm test`, start `fods serve`, run the
   deterministic demo, click a citation, open the brief drawer, open Lab and Trace, press New
   investigation, run the Docker image. Report each step honestly, including failures.
2. Write `docs/SUBMISSION_REPORT.md`: what changed; **every** finding in `AUDIT_FINDINGS.md`
   (UI-01 to UI-11, A-01 to A-15) with status fixed / deferred + reason / accepted risk, each
   with its test or evidence; measured test counts before and after; before/after screenshots
   for every UI item; what was **NOT verified** (for example live provider behaviour, Ollama
   planner, DNS-rebinding, Docker if unavailable); known limitations; 5-minute demo steps.
3. Then **stop and ask the owner how to land the work** (merge into `main` or open a PR). Do not
   merge on your own. `main` does not contain the source tree, so the submission branch must
   contain `src/fods/`, the frontend, Docker files and docs together.

## 7. Reporting format

Short and factual. After every commit: what changed (3 lines), real gate output lines, what is
next. When blocked: say exactly what failed, the error text, what you tried, and the options.
Do not pad.

**Begin with section 2.**
