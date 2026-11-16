# Next Slice 9 Prompt

Implement slice 9 only: cleanup, accessibility, docs, screenshots, Docker rebuild. Do not start new feature work.

## Scope

1. Rebuild the Docker image so it serves the new shell from `src/fods/web/dist`.
2. Remove Playwright from any Docker build or runtime image. Keep it dev-only.
3. Final a11y pass:
   - keyboard navigation for every interactive surface
   - focus rings visible
   - no color-only status
   - reduced-motion support where animation exists
4. Final docs:
   - update README commands so they match the working venv commands
   - document `FODS_API_PORT`
   - document the new shell routes
5. Screenshot set:
   - refresh slice screenshots at 1280 px and 768 px for light and dark themes
   - include RLA and FODS Lab states
6. Cleanup:
   - remove scratch files from the repo root (`full_test.out`, `run.log`, `results*.txt`, `test_out.txt`, `test_output.txt`, `test_p8_gap.out`)
   - verify `.gitignore` still keeps `data/graph/`, `.env`, `.e2e-data/`, and `dist/` ignored
7. Re-run the full gate and record exact numbers in `docs/audit/PROGRESS.md`.

## Constraints

- Do not touch the 82 original logs.
- Do not regenerate `data/corpus.json`, `data/extractions.jsonl`, or `data/concepts.json`.
- Do not add dependencies without pinning them exactly and checking the licence.
- Do not claim passing without real command output.
- Keep the per-slice gate:
  - `pytest tests/ -q`
  - `ruff check src/ tests/`
  - `npm run build`
  - `npm test`
  - `npm run test:e2e`
  - one commit plus a 3-line status

## Acceptance criteria

- Docker on 8765 serves the new UI.
- `rla doctor` and `rla sources` work from a clean checkout.
- `npm run test:e2e` passes with the Docker-served build.
- Zero CSP violations and zero console errors in the e2e run.
- README commands work as written.

## Do not do

- Do not implement a new slice.
- Do not change backend behaviour unless a slice-9 bug requires it.
- Do not delete the 7 extra demo runs without owner permission.
