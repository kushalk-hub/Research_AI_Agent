# FODS Research Studio Frontend Acceptance Report

**Status:** In progress; production frontend acceptance is not complete.  
**Repository state:** `codex/fods-mvp-acceptance`, baseline `f533ae1ea8b0af7bdf99a6fee0d9f44d3b267ed8` with pre-existing uncommitted work preserved.

## Implemented in this continuation

- Replaced visible Chat terminology with Research / New investigation and added a Library route. Kept the classic workbench at `/?legacy=1`.
- Added backend-backed provider configuration, run history and saved-context views.
- Live browser runs reject a fixture planner. An automatic live planner resolves to the configured Ollama planner, and a non-Ollama structured provider is rejected rather than silently downgraded.
- Forwarded the source-cache bypass option to the real `_execute` implementation and require it to be used only for live mode.
- Pass the selected saved-context hash to the production executor and validate its snapshot before run creation.
- Added trace filtering, a readable event inspector with collapsed raw payload, exact run-question display, and evidence links from recorded DOI/HTTP(S) URLs.
- Removed fabricated worker slot numbering. The visualizer shows active tasks at the selected event, distinguishes unrecorded queue state from a recorded empty queue, and reconstructs per-task LIFO frames at the selected cursor.
- Vendored pinned D3 `d3-path` 3.1.0 and `d3-shape` 3.2.0 with licenses, served them from the same-origin app, and use the D3 line generator for curved DAG edges. The DOM renderer remains `shell.js`.
- Added regression coverage for the corrected behavior.

## Verification

- Focused production web, frontend projection, runtime and visualization tests: **44 passed, 1 skipped**.
- Provider routing and acceptance modules: **82 passed**.
- Extraction/acquisition-order and extraction-resume checks: **2 passed**; the tests use a no-embedder path because resolution is not their subject and must not call a provider.
- Full suite: `\.venv\Scripts\python.exe -m pytest tests/ -q --basetemp=.pytest-tmp/fods-studio-final-4` — **803 passed, 1 skipped, 0 failed; 804 collected; 271.32s**.
- Ruff: `\.venv\Scripts\ruff.exe check src/ tests/` — **exit 0, all checks passed**.
- Compilation: `\.venv\Scripts\python.exe -m compileall src/fods` — **exit 0**.
- Windows pytest needed local loopback access to create asyncio socket pairs and serve the HTTP test fixtures. All temporary test data stayed under `.pytest-tmp/`.
- The live-provider preflight reported planner model configured as `ollama/qwen3:4b`, but the Ollama endpoint was unreachable. Gemini had a key configured, but `RLA_FODS_ALLOW_GEMINI` was not enabled. No credential values were printed.
- Windows Computer Use reported that local browser use is disabled by Work settings. No production browser walkthrough or screenshot is claimed.

## Remaining acceptance gates

- Extend D3 use to interactive pan/zoom or additional geometry only if needed; the DAG path geometry already uses the pinned local D3 shape library. Node positions use runtime-provided topological levels.
- Instrument true heap-array snapshots if a heap-tree view is required. The current runtime snapshot is a selection-ordered queue view.
- Keep worker lanes unnumbered unless the runtime provides actual worker identities.
- Run a complete live browser investigation with the real configured planner, fresh academic requests, actual answer provider, persisted brief/trace and Library replay after provider and browser access are available.
- Capture genuine production screenshots with run ID, mode, event cursor and provenance. See [`fods_screenshot_inventory.md`](fods_screenshot_inventory.md).

The product implementation and automated regressions are in place, but M6 live end-to-end acceptance and the screenshot-dependent part of M7 remain blocked by the unavailable configured Ollama service and the Work setting that disables local browser control. These gates are not marked passed.

The knowledge graph remains an explicit CLI capability and is not invoked by normal research submission or update.
