# Coding Agent Prompt

Copy everything below into the coding agent.

```text
You are continuing the FODS Research Studio frontend rebuild on branch `feature/studio-redesign`.

First read these files in this order:
1. AGENTS.md
2. docs/FRONTEND_DESIGN.md
3. docs/audit/AUDIT_FINDINGS.md
4. docs/audit/PROGRESS.md
5. docs/agent_handoff/CURRENT_STATE.md
6. docs/agent_handoff/NEXT_SLICE_9_PROMPT.md

Before baseline checks, verify dependencies:
- git, gh, Python 3.12, Node, npm, Docker
- Ollama with `qwen3:4b` and `nomic-embed-text`
- Playwright Chromium via `npx playwright install chromium`
- `.env` exists; `GEMINI_API_KEY` is optional

Then run the baseline checks from docs/agent_handoff/SETUP_AND_COMMANDS.md. Do not edit anything until all baseline checks pass.

Current state:
- Last completed slice: slice 8 (FODS Lab), committed as `feat(ui): FODS Lab (slice 8)`.
- Next slice: slice 9 (Docker rebuild, cleanup, a11y, docs, screenshots).
- Baseline: pytest 859 passed / 1 skipped; ruff clean; vite build 55.70 kB css / 349.76 kB js; vitest 242 passed; Playwright 11 passed.

Rules you must follow:
- Work only on `feature/studio-redesign`. Never commit onto `codex/research-frontend-5paper-checkpoint` or `main`.
- Use `.venv\Scripts\python.exe`, not the Python on PATH.
- Do not touch the 82 original logs in `data/fods/runs/`.
- Do not regenerate `data/corpus.json`, `data/extractions.jsonl`, or `data/concepts.json`.
- Do not claim passing without real command output.
- Zero CSP violations on `fods serve`: no dangerouslySetInnerHTML, no setAttribute('style', ...), no inline style attributes.
- Playwright is dev-only and must not enter Docker.
- New dependencies must be pinned exact and have a licence.
- Evaluation honesty rules in AGENTS.md are non-negotiable.

Task:
Implement slice 9 only, following docs/agent_handoff/NEXT_SLICE_9_PROMPT.md. Rebuild Docker, final a11y, docs, screenshots, cleanup. Do not implement any other slice.

Per-slice gate:
- `pytest tests/ -q`
- `ruff check src/ tests/`
- `npm run build`
- `npm test`
- `npm run test:e2e`
- one commit plus a 3-line status

Stop for review after slice 9. Do not start a new slice.
```
