# Benchmark Integrity Audit — 2026-10-31

**Branch:** `codex/phase2-1-verification`  
**Audit date:** 2026-10-31  
**Audit method:** Direct inspection of all 20 event logs (`data/fods/runs/Q01..Q10-{quick,deep}.jsonl`), paired collector output (`benchmarks/paired_review_20261031.csv`), pooled worksheet (`benchmarks/pooled_review_20261031.csv`), source code, and tests. No live calls, model calls, or frontend changes were made.

## 1. Benchmark collection summary

- 20 live runs completed (10 Quick + 10 Deep) using `--mode live --planner fixture --fresh-sources`.
- Gemini opt-in unset; zero model-call events in all 20 logs.
- HTTP attempts: 87 total (semantic_scholar 27, openalex 20, arxiv 20, crossref 10, dblp 10).
- Max in-flight concurrency: 1 for every observed provider.
- 19 HTTP 429 responses, all semantic_scholar, all recovered via retry (0 terminal).
- 30 cancelled source-query tasks; 200 completed search tasks; 230 planned (matches profile caps: 10×3 Quick + 10×5×4 Deep).
- Review pack: `benchmarks/paired_review_20261031.csv` (650 rows, blank labels).
- Quality status: **Quality evaluation: NOT YET PERFORMED — evaluation method to be decided separately.**

## 2. Candidate identity and count reconciliation

Definitions:
- A **query–paper observation** is one row in a run's retained context (paper × run). It is not necessarily a globally distinct paper.
- A paper can appear under multiple research questions because all queries share the topic "Graph attention networks" and the base source query is the topic.

Verified from logs:
- Per run: raw = processed = unique = retained (duplicates_merged = 0 in all 20 runs; 650 raw → 650 unique total).
- Quick: 20 retained per run × 10 = 200 observations.
- Deep: 45 retained per run × 10 = 450 observations.
- Total distinct run-level observations: 650 (matches paired CSV rows).
- Cross-run identity: the same paper identities recur across all 10 queries (topic-driven retrieval). Deep's candidate set is a superset of Quick's for every query (200 Quick observations all present in Deep; 0 Quick-only). Pooled worksheet: 450 unique query–paper observations (45/query), 200 with both ranks.
- Union of top-10 Quick+Deep: 148 observations per the collector's row-level view; this is a row-count, not a distinct-paper count.

Deduplication note: within each run, dedup on strong IDs (DOI, arxiv_id, external_ids) then normalized title+year found zero merges. This may indicate disjoint ID spaces across sources or missed normalization of preprint/published variants; not investigated further here. No CSV changes made.

## 3. Source-query behavior

- With the fixture planner (no LLM), `ResearchQueryPlan` uses `_rule_queries` (deterministic rules). Intent classified as `other` for all 10 questions (none match the intent keyword lists), so aspect = "research findings evidence".
- Deep query_count = 4: queries are topic, topic+aspect, topic+full question, topic+recent research. Quick query_count = 1: only the topic.
- All source requests use these topic-derived phrases; the complete research question is used only in ranking (question_coverage term weighting) and evidence selection, not as the source search phrase.
- Conclusion: This experiment tests **topic-level retrieval + question-conditioned ranking + Quick vs Deep retrieval depth**, not question-specific search-query generation. Claiming effective question-specific query generation would be unsupported. A question-specific benchmark is recommended as future work (not executed).

## 4. Quick versus Deep retrieval behavior

- Deep extends Quick by expanding search: 5 sources × 4 queries vs 3 sources × 1 query.
- Deep's retained set is a superset of Quick's (100% overlap of Quick papers) because Deep includes the same base topic query and the same OpenAlex/arXiv base results, plus additional sources/queries.
- Shared candidates' scores are computed by the same `rank_candidates` function (topic_coverage×50 + question_coverage×30 + abstract×8 + new_source×5 + new_query×3). However, ranks may differ because the candidate pool and greedy coverage state differ between profiles.
- Profile limits enforced: Quick max_retained 20, target 8; Deep max_retained 50, target 25. Source limits: Quick 3, Deep 5.
- Quick contributed sources: openalex + arxiv in all 10 runs (semantic_scholar consistently cancelled due to 429 retry + quorum). Deep: all 5 providers in all 10 runs.

## 5. Evidence selection and citation findings

- Evidence selected: Quick 60 (avg 6/run), Deep 80 (avg 8/run). Selection uses `rank_candidates` then token-budget truncation (max 6/8 cards, 6000/12000 token budget).
- Citation occurrences: 30 per profile (3/run). Root cause: the deterministic (no-LLM) answer formatter hard-codes `evidence[:3]` — only the top 3 selected cards are rendered as citations. The remaining selected evidence is available to the brief generator's evidence list but not cited.
- `citation_validation` checks citation-ID existence only: all `[P\d+]` in the answer must belong to the allowed set (selected evidence citations). It does not verify claim-level factual support (`claim_support = "unverified"` in all 20 runs). Validation is per run (per answer), not per candidate.
- No model calls were made; answers were produced by the deterministic formatter, not Qwen/Gemini.

## 6. Latency definitions and corrected measurements

Timing fields:
- `context_ready.elapsed_ms` = start-to-answerable-context duration = (perf_counter − run_started) + pre_execution_ms. (Previously labeled "acquisition latency".)
- `run_finished.elapsed_ms` = total run duration = (perf_counter − run_started) + pre_execution_ms.
- No separate "pure acquisition duration" (source-call-only) is recorded.

Corrected medians (from event logs):
| Measurement | Quick (n=10) | Deep (n=10) |
|---|---:|---:|
| Start-to-answerable-context duration (median ms) | 1812 | 2275 |
| Total run duration (median ms) | 1858 | 2347 |

`21.md` and collection report timing labels updated accordingly.

## 7. Provider request and rate-limit findings

- HTTP 429: 19 total, all semantic_scholar, all recovered via retry (retry_decision=retry), 0 terminal failures.
- Cancelled tasks: 30 (optional source tasks stopped when quorum/target reached). 18 HTTP attempts were started but cancelled before a response (counted in attempt budget, no response event).
- Source-query tasks: 230 planned, 200 completed, 30 cancelled.
- Attempt budget: applied per run (Quick 24, Deep 160 max), not across the whole benchmark. Total budget_used = 87.
- Provider contributions to retained candidates: Quick = openalex + arxiv (10 runs each); Deep = all 5 providers (10 runs each). semantic_scholar never contributed in Quick (cancelled each run).
- SerpApi policy: max_in_flight = None (not provider-limited); SerpApi was not an enabled source in this benchmark, so no SerpApi concurrency was observed. The "max in-flight = 1 for all observed providers" statement applies only to observed providers.

## 8. Model-call status

- Model-call events: 0 across all 20 runs.
- Planner: fixture (deterministic rules), no Ollama.
- Answer: deterministic formatter, no Gemini.
- Gemini opt-in: unset throughout.

## 9. Remaining technical limitations

1. Deduplication found zero merges within runs; cross-source identity (DOI/arxiv/title) may miss preprint/published variants — not verified.
2. Quick's semantic_scholar source is consistently cancelled (429 retry + quorum), so Quick effectively uses only OpenAlex + arXiv.
3. Citation count capped at 3 by deterministic formatter; selected evidence (6/8) exceeds cited (3).
4. Citation validation checks ID existence only, not claim-level support (claim_support = unverified).
5. Retrieval is topic-level, not question-specific (base search phrase = topic).
6. Qwen live enrichment blocked by Ollama timeout (unchanged from Phase 2.1).
7. Concept graph and reference discovery broader testing pending.

## 10. Recommended next engineering milestone

Small, logically ordered:
1. Restore Ollama and run a bounded Qwen enrichment smoke (1 batch), verify cache validation/provenance.
2. Improve citation output to use more of the selected evidence (configurable cap) and add claim-level support marker handling.
3. Investigate cross-source dedup (DOI/arxiv/title normalization) with fixture tests.
4. Add a retrieval-only mode (no answer/write) for future benchmarking, if desired.
5. Re-run provider preflight and, if needed, a small live smoke.

No human review, AI evaluation, new collection, frontend work, or commit in this milestone.

## Verification

- `pytest tests/ -q` → 734 passed (160.15 s).
- `ruff check src/ tests/` → All checks passed.
- `compileall -q src/fods src/rla` → passed.
- All audit computations derived from event logs and code; no live calls made.