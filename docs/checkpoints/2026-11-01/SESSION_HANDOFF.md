# FODS Research Agent — Session Handoff

**Checkpoint:** [Project state](PROJECT_STATE.md)  
**Roadmap:** [Next phase plan](NEXT_PHASE_PLAN.md)  
**As-of:** 2026-11-01

## Owner decision revision

The owner explicitly waived the human-review benchmark as a prerequisite for starting frontend development. This does not mean the benchmark passed: paired and pooled review sheets remain blank and preserved, and no retrieval-quality claim is authorized. Continue the frontend using labeled synthetic fixtures, preserve the classic workbench and accepted backend/data baseline, and report browser/manual evidence separately from automated tests.

The latest owner direction narrows the current task to a design proposal and separate static prototype. Do not change the production frontend or backend until the owner reviews and approves the new design/prototype. The previous limited shell implementation is preserved as current code, not treated as approval of the redesign.

## Purpose

FODS Research Agent is a FODS course project that turns a bounded research question into a cited brief while making task dependencies, scheduling, state, evidence, and recovery observable. The core rule is **the LLM suggests; the FODS runtime governs**. Backend acceptance passed, but the complete product and presentation are not finished.

## Read these first

1. [`AGENTS.md`](../../../AGENTS.md) — repository conventions and environment.
2. [`docs/master.md`](../../master.md) — project purpose and scope.
3. [`README.md`](../../../README.md) — repository entry points.
4. [`PROJECT_STATE.md`](PROJECT_STATE.md) — inspected implementation, benchmark and frontend status.
5. [`NEXT_PHASE_PLAN.md`](NEXT_PHASE_PLAN.md) — gated milestones and acceptance criteria.
6. [`docs/design/frontend_design_research.md`](../../design/frontend_design_research.md) — frontend proposal, not implemented UI.
7. [`docs/fods_assessment_demo_guide.md`](../../fods_assessment_demo_guide.md) and [`docs/fods_demo_artifact_inventory.md`](../../fods_demo_artifact_inventory.md) — current demo capabilities and artifact provenance.

## Repository checkpoint

- Repository: `D:\Research_AI_Agent-fods`
- Active branch: `codex/fods-mvp-acceptance`
- HEAD and origin branch: `f533ae1ea8b0af7bdf99a6fee0d9f44d3b267ed8` (`Fix cross-platform FODS output path validation`)
- Accepted CI: run [41296050154](https://github.com/kushalk-hub/Research_AI_Agent/actions/runs/41296050154), 797 full tests, 28 P4 tests, Ruff and compilation passed; fixture run `a358ed9efa63`, 8 tasks, four papers/evidence cards, IDs P1/P2/P3 validated.
- The working tree was already dirty before this checkpoint: README/demo/completion documentation edits, four new demo guides, and untracked `.pytest-tmp/`. Preserve those changes. Checkpoint files are also new/uncommitted. Do not reset, clean, commit, or push unless explicitly instructed.

## Completed backend milestones

Plan validation and cycle rejection, DAG readiness, FIFO/priority scheduling, bounded workers/retries, task-ID state, per-task stacks, runtime events/JSONL, normalization/context persistence, evidence selection, citation-ID validation, workspace-safe output, replay, and optional graph build/update/query are implemented. CI acceptance is for the deterministic fixture/backend scope. Citation-ID membership is not semantic support. The current CLI graph workflow is optional and separate from normal research runs.

## Current frontend

The owner has since approved production implementation of the Research Studio. The default page now exposes Research, Trace, FODS Lab, and Library navigation over the existing run/context APIs, while `/?legacy=1` keeps the classic workbench accessible. Live requests reject fixture planning, saved context selection carries the immutable snapshot hash, and source-cache bypass reaches the production executor. The visualizer shows active tasks without inventing worker IDs, distinguishes missing queue state from recorded-empty state, and reconstructs stacks at the selected cursor. Pinned local `d3-path` and `d3-shape` assets generate DAG edge paths; `shell.js` owns the SVG DOM. The frontend remains in progress: the configured Ollama planner is unreachable, and the Gemini FODS opt-in is disabled.

The prior browser attempt encountered Windows loopback `WSAEACCES`; this continuation is verifying the production server again. Do not claim a real live browser demonstration or create illustrative screenshots as if captured. Do not change firewall, antivirus, or other security settings to work around the restriction.

## Pending benchmark evaluation (not a frontend blocker)

Both review sets are unlabelled: paired sheet 650 rows (200 Quick/450 Deep), pooled sheet 450 rows. The owner waived this review as a prerequisite for frontend implementation, but did not mark it passed. Preserve the source sheets; make dated copies before any later review. Reviewer identity/disagreement, pooled scoring, and a quantitative threshold remain undecided.

The paired sheet supports `python -m fods.benchmark score`; the pooled sheet has a different schema and must not be passed to that scorer. `tools/mammoth_evaluator` performs model-assisted judgments and is not human review. Preserve existing sheets by making dated working copies. See Phase 1 in `NEXT_PHASE_PLAN.md` for exact fields, labels, commands, scoring, and acceptance conditions.

## Next executable task

1. Add any required D3 interactions (such as pan/zoom) without migrating from the static frontend; the current dependency edges already use pinned local D3 path geometry.
2. Complete the required production browser/UI regression checks and run focused/full tests, Ruff and compileall.
3. Re-run a live browser investigation only after the configured Ollama planner is reachable; enable Gemini for FODS only by the owner's explicit environment configuration.
4. Record screenshots only from actual production runs. Keep simulated runs clearly labelled and separate from live evidence.
5. Later, if retrieval-quality evaluation remains a project requirement, obtain human-review protocol decisions, work from dated copies, and score only supported paired data. This evaluation is independent of the frontend authorization.

## Architecture boundaries and protected data

- FODS runtime owns plan validation, readiness, scheduling, task execution and event state. Browser code renders this state; do not create a second scheduler in the UI.
- `src/rla/` is the companion pipeline/package; `src/fods/` is the primary FODS runtime/app.
- Preserve `data/fods/` contexts/enrichments, benchmark source CSVs, accepted CI artifacts, and fixture traces/briefs.
- Original graph at `data/fods/knowledge_graph/887437c0b2403e8b/graph.json` is schema v1 (32 paper records). Isolated schema-v2 demo is in `.pytest-tmp/mvp-existing-context-demo-99861ac9`; never overwrite or conflate them.
- Fixture simulation is not live retrieval; replay is not fresh execution; citation-ID validation is not entailment evaluation.
- Do not create slides/PPT in the next continuation. The user plans to review the docs/demo package before presentation material.

## Useful inspection commands

Run from the repository root in PowerShell:

```powershell
git status --short --branch
git rev-parse HEAD
git log -8 --oneline --decorate
.\.venv\Scripts\python.exe -m pytest tests/test_fods_webapp.py tests/test_fods_runtime.py tests/test_fods_benchmark.py -q
.\.venv\Scripts\python.exe -m fods.cli serve --host 127.0.0.1 --port 8765
python -m fods.benchmark score --input benchmarks/paired_review_human_YYYYMMDD.csv `
  --output benchmarks/paired_metrics_human_YYYYMMDD.json --k 5 10
```

The test and server commands above are for the next verification pass; they were not run as part of this documentation checkpoint. Start the server only for the browser baseline. If loopback access is blocked, record it and use saved artifacts without changing security settings.

## Reporting rule

Keep automated API tests, CI acceptance, manual browser verification, screenshots, provider runs, and human relevance judgments as separate evidence categories. Report a step as passed only when its stated test or demonstration evidence exists.
