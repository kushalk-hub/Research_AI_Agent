# Current State

## Branch and commits

- Branch: `feature/studio-redesign`
- Base: `codex/research-frontend-5paper-checkpoint` at `3081afb`
- Last commit: `feat(ui): FODS Lab (slice 8)`

Completed slices and their commits:

1. `ce8fbd1` - step 1
2. `dcad428` - slice 1
3. `4e1ca1c` - slice 1.1
4. `8cd8af1` - backend
5. `e98957b` - slice 2
6. `b65dc77` - slice 3a
7. `a858f7a` - slice 3b
8. `a4e475d` - slice 4
9. `6069670` - slice 5
10. `8d8d825` - slice 6
11. `bc2e0d2` - slice 7
12. slice 8 - FODS Lab (this handoff)

## What is implemented

- Research thread, composer run-settings, live gating, budget override.
- Backend display fields, tolerant logs, disk stream fallback, path hygiene.
- Answer and evidence with resolvable citations.
- Brief drawer with rendered Markdown.
- Execution trace (virtualised table, waterfall, detail pane).
- FODS Lab: RLA phase rail and FODS dependency DAG, queue, worker slots, stacks, state table, playback, captions.

## Frontend entry points

- `stitch_aesthetic_markdown_reader/src/App.jsx`
- `stitch_aesthetic_markdown_reader/src/views/LabView.jsx`
- `stitch_aesthetic_markdown_reader/src/views/TraceView.jsx`
- `stitch_aesthetic_markdown_reader/src/views/LibraryView.jsx`
- `stitch_aesthetic_markdown_reader/src/lib/lab.js`
- `stitch_aesthetic_markdown_reader/src/lib/trace.js`
- `stitch_aesthetic_markdown_reader/src/lib/events.js`

## Backend entry points

- `src/fods/webapp.py`
- `src/fods/event_meta.py`
- `src/fods/runtime.py`
- `src/fods/cli.py`

## Tests and baselines

- pytest: `859 passed, 1 skipped`
- ruff: clean
- vite build: `55.70 kB css / 349.76 kB js`
- vitest: `242 passed in 21 files`
- Playwright: `11 passed`

## Known limitations

- No live RLA run on a keyless machine; RLA UI is exercised against the committed log `efee736eb669`.
- Docker on 8765 still serves the old UI; slice 9 rebuilds it.
- `data/fods/runs/` contains 7 extra demo runs created during slice 1/1.1 checks. They are not deleted.
- The 82 original logs must never be touched.

## Files changed for slice 8

- `stitch_aesthetic_markdown_reader/src/lib/lab.js`
- `stitch_aesthetic_markdown_reader/src/lib/lab.test.js`
- `stitch_aesthetic_markdown_reader/src/views/lab/PhaseRail.jsx`
- `stitch_aesthetic_markdown_reader/src/views/lab/PlanGraph.jsx`
- `stitch_aesthetic_markdown_reader/src/views/lab/QueuePanel.jsx`
- `stitch_aesthetic_markdown_reader/src/views/lab/StackPanel.jsx`
- `stitch_aesthetic_markdown_reader/src/views/lab/StateTable.jsx`
- `stitch_aesthetic_markdown_reader/src/views/lab/PlaybackBar.jsx`
- `stitch_aesthetic_markdown_reader/src/views/LabView.jsx`
- `stitch_aesthetic_markdown_reader/src/views/LabView.test.jsx`
- `stitch_aesthetic_markdown_reader/src/app/App.jsx`
- `stitch_aesthetic_markdown_reader/src/store/reducer.js`
- `stitch_aesthetic_markdown_reader/src/styles/app.css`
- `stitch_aesthetic_markdown_reader/src/test/setup.js`
- `stitch_aesthetic_markdown_reader/src/views/views.test.jsx`
- `stitch_aesthetic_markdown_reader/e2e/studio.spec.js`
- `docs/audit/PROGRESS.md`
- `docs/audit/screenshots/slice8-*.png`
