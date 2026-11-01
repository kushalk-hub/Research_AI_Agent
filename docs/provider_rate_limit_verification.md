# Provider Rate-Limit Verification

**Date:** 2026-10-31
**Branch:** `codex/phase2-1-verification`
**Status:** Offline tests pass; Q01–Q10 paired live collection completed (87 HTTP attempts, no throttling failures).

## 1. Provider policies (before and after)

Before the changes, only Semantic Scholar had any pacing (1.1 s via `RateLimiter`, applied only to that adapter). arXiv, DBLP, and Crossref inherited `min_interval = 0`, and the scheduler's worker concurrency (3) was the only bound. OpenAlex had no header handling. None of the providers enforced in-flight serialization or cross-process coordination, and retries did not pass through provider pacing.

After the changes, every outbound HTTP attempt passes through a `ProviderRequestLimiter` at the `Fetcher` boundary:

| Provider | Min start interval | Max in-flight | Header policy | Cross-process lock |
|---|---:|---:|---|---|
| arXiv | 3.0 s | 1 | none | enabled |
| DBLP | 2.0 s | 1 | none (Retry-After honored) | enabled |
| Crossref | 1.0 s (default; headers may tighten) | 1 | crossref (`x-rate-limit-*`, `x-concurrency-limit`, `x-api-pool`) | enabled |
| OpenAlex | 1.0 s | 1 | openalex (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) | enabled |
| Semantic Scholar | max(1.1, `s2_delay_seconds`) s | 1 | none (Retry-After honored) | enabled |
| SerpApi | 0.5 s | not provider-limited | none | enabled |

References: [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html), [DBLP crawler/rate-limit guidance](https://dblp.org/faq/1474706.html), [Crossref REST API access and limits](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/), [Crossref rate-limit changes](https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/), [OpenAlex authentication/rate limits](https://help.openalex.org/api/authentication/).

## 2. Files changed

- `src/rla/store/rate_limits.py` (new): `ProviderPolicy`, `ProviderRequestLimiter`, `LiveCollectionLock`, `RequestAttemptBudget`, `parse_retry_after`, `outbound_request_context`, telemetry helpers.
- `src/rla/store/cache.py`: `Fetcher` routes every attempt through `provider_limiter`; retries reuse the same limiter; `Retry-After` (delta seconds or HTTP date) honored as a minimum wait combined with the provider interval; bounded backoff; attempt budget enforcement; sanitized telemetry emission.
- `src/rla/pipeline/acquisition.py`: `build_sources` attaches a `ProviderRequestLimiter` per provider with machine-local shared lock directory; Semantic Scholar interval respects `s2_delay_seconds`.
- `src/fods/sources.py`: `selected_live_source_names` and `build_live_source_pool(..., attempt_budget=...)`.
- `src/fods/tools.py`: search and reference-discovery handlers run inside `outbound_request_context` so deadlines and telemetry propagate; rate-limit/budget exceptions are not swallowed.
- `src/fods/runtime.py`: outbound request deadline computed from acquisition/workflow deadlines; run-finished telemetry includes HTTP attempts, per-provider counts, max in-flight, budget usage.
- `src/fods/cli.py`: offline `preflight` command; `LiveCollectionLock` guards live runs; per-run `RequestAttemptBudget`; provider telemetry in the research summary; no-overwrite guards for brief/event-log paths.
- `tests/test_provider_rate_limits.py` (new): 13 tests.
- `tests/test_p1_acquisition.py`: updated Retry-After HTTP-date test.

No frontend files, `.env`, credentials, or dependency pins were changed.

## 3. Test commands and results

- `.\.venv\Scripts\python.exe -m pytest tests/test_provider_rate_limits.py -q` → **13 passed**.
- `.\.venv\Scripts\python.exe -m pytest tests/ -q` → **734 passed in 160.15 s**.
- `.\.venv\Scripts\python.exe -m ruff check src/ tests/` → **All checks passed**.
- `.\.venv\Scripts\python.exe -m compileall -q src/fods src/rla` → passed.
- `.\.venv\Scripts\python.exe -m fods.cli preflight --pair` → reported policies and budgets without network calls.

## 4. Dry-run policy report

From `fods.cli preflight --pair`:

- Quick: sources semantic_scholar, openalex, arxiv; 3 planned source-query tasks; hard HTTP attempt budget 24.
- Deep: sources semantic_scholar, openalex, arxiv, crossref, dblp; 20 planned source-query tasks; hard HTTP attempt budget 160.
- Combined: 23 planned source-query tasks; 184 hard HTTP attempt budget.
- Semantic Scholar min interval 1.1 s; arXiv 3.0 s; DBLP 2.0 s; Crossref 1.0 s; OpenAlex 1.0 s. All max in-flight 1. Cross-process lock enabled for all.

## 5. Observed telemetry (Q01–Q10, 20 runs)

- Total HTTP attempts: **87** (planned ceiling 230 source-query tasks; retries included).
- By provider: semantic_scholar 27, openalex 20, arxiv 20, crossref 10, dblp 10.
- Max in-flight observed: 1 for every provider.
- Stop reasons: 10 × `source_quorum_reached` (Quick), 10 × `unique_paper_target_reached` (Deep).
- Model-call events: 0 (Gemini opt-in unset; fixture planner used).
- No 429 was retried before its required wait; no quota errors; no budget exhaustion.

## 6. Cross-run coordination

The `LiveCollectionLock` (nonblocking file lock under `data/fods/provider-locks/live-collection.lock`) prevents overlapping live collections in one workspace. Provider lock files (`{provider}.lock`) persist `last_start`/`not_before` across processes, so sequential runs honor the spacing even across separate CLI invocations.
