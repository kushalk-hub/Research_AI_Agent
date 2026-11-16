# FODS Research Studio - Team Handoff

This repository is the FODS Research Studio frontend rebuild. The handoff below is for a teammate
who will continue the work in a new clone or on another machine.

## Current branch and state

- Working branch: `feature/studio-redesign`
- Base commit: `codex/research-frontend-5paper-checkpoint` at `3081afb`
- Last completed slice: **slice 8 (FODS Lab)**, committed as `feat(ui): FODS Lab (slice 8)`
- Previous slices complete and committed: slice 0, 1, 1.1, backend, slice 2, 3a, 3b, 4, 5, 6, 7
- Next slice to implement: **slice 9 (Docker rebuild, cleanup, a11y, docs, screenshots)**
- Do not implement slice 9 in this handoff commit. Start it only after the teammate reviews this state.

## Important rules (do not break)

1. Work only on `feature/studio-redesign`. Do not commit onto `codex/research-frontend-5paper-checkpoint` or `main`.
2. Never touch the 82 original logs in `data/fods/runs/`. There are 7 extra demo runs from manual checks; ask before deleting them.
3. Do not regenerate or reformat `data/corpus.json`, `data/extractions.jsonl`, or `data/concepts.json`.
4. `src/` is a src-layout package; `src/rla` imports itself as `rla`, never `src.rla`.
5. Use the venv's tools, not the tools on PATH.
6. Never claim fixed/passing/building without real command output. "NOT VERIFIED" is acceptable.
7. Zero CSP violations on `fods serve`; no `dangerouslySetInnerHTML`, no `setAttribute('style', ...)`, no inline `style` attributes.
8. Playwright is dev-only and must not be added to Docker.
9. New dependencies must be pinned exact and have a licence.
10. Evaluation honesty rules in `AGENTS.md` are non-negotiable.

## Where to start

Read these files first:

1. `AGENTS.md`
2. `docs/FRONTEND_DESIGN.md`
3. `docs/audit/AUDIT_FINDINGS.md`
4. `docs/audit/PROGRESS.md`
5. `docs/agent_handoff/CODING_AGENT_PROMPT.md`

Then run the baseline checks in `docs/agent_handoff/SETUP_AND_COMMANDS.md`.
