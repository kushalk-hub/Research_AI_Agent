# Paired Quick/Deep Retrieval Benchmark — Collection Report

**Collection date:** 2026-10-31  
**Branch:** `codex/phase2-1-verification`  
**Status:** **COMPLETE — 10/10 PAIRED QUICK/DEEP LIVE RUNS COLLECTED**  
**Quality verdict:** **PENDING HUMAN REVIEW**

## Decision (updated 2026-10-31)

Provider-specific pacing was implemented in `src/rla/store/rate_limits.py` and routed through the `Fetcher` boundary (see `docs/provider_rate_limit_verification.md`). A no-network preflight (`fods.cli preflight --pair`) confirmed all policies. The Q01 pilot then ran and passed all health checks, so collection continued through Q10 under the approved staged rule. All 20 runs completed; 87 HTTP attempts total (ceiling 230 source-query tasks). No quota errors, no budget exhaustion, no corrupted contexts. Quality remains **PENDING HUMAN REVIEW**.

## Collection results

| Measure | Quick (n=10) | Deep (n=10) | Total (n=20) |
|---|---:|---:|---:|
| Runs completed | 10 | 10 | 20 of 20 |
| Raw candidates | 200 | 450 | 650 |
| Processed candidates | 200 | 450 | 650 |
| Unique papers | 200 | 450 | 650 |
| Retained context papers | 200 | 450 | 650 |
| Selected evidence papers | 60 | 80 | 140 |
| Cited papers | 30 | 30 | 60 |
| HTTP attempts | 37 | 50 | 87 |
| Acquisition latency median (ms) | 1812 | 2275 | — |
| Total latency median (ms) | 1858 | 2347 | — |

HTTP attempts by provider across all 20 runs: semantic_scholar 27, openalex 20, arxiv 20, crossref 10, dblp 10 = 87. Max in-flight observed: 1 for every provider. Stop reasons: 10 × `source_quorum_reached` (Quick), 10 × `unique_paper_target_reached` (Deep). Model-call events: 0 (Gemini opt-in unset; fixture planner used).

All ten Quick/Deep pairs completed. No throttling failures, no quota errors, no budget exhaustion, no corrupted contexts. The historical practice pack was not used as a substitute. A new blank-label review pack was collected from exactly these 20 logs: `benchmarks/paired_review_20261031.csv` (650 candidate rows).

The benchmark remains explicitly **PENDING HUMAN REVIEW**. There are no measured relevance or quality results and no basis for claiming Deep is better.

## Artifacts

- Event logs: `data/fods/runs/Q01-quick.jsonl` … `Q10-quick.jsonl` and `Q01-deep.jsonl` … `Q10-deep.jsonl` (20 files).
- Briefs: `data/fods/briefs/Q01-quick.md` … `Q10-quick.md` and `Q01-deep.md` … `Q10-deep.md` (20 files).
- Context snapshots and HTML visualizations alongside the run logs.
- Review pack: `benchmarks/paired_review_20261031.csv` (650 blank-label rows).

## Human-review instructions

Review each candidate row in `benchmarks/paired_review_20261031.csv` and set `reviewer_label` to `relevant`, `not_relevant`, or `uncertain`, plus optional notes. Mark `judged_pool_complete=true` only when the whole query/profile pool is judged. Score afterward with `python -m fods.benchmark score --input benchmarks/paired_review_20261031.csv --output benchmarks/paired_metrics_20261031.json --k 5 10`. Quality remains **PENDING HUMAN REVIEW** until valid binary labels exist.

## Preservation and worktree status

All pre-existing untracked artifacts were preserved. No frontend files, `.env`, credentials, or dependency pins were changed. No commit was created.