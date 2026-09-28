# LLM Provider Validation — Real-Provider Report

**Date:** 2026-09-28
**Objective:** Validate the provider-routing implementation against a real provider.
**Provider exercised:** Google Gemini, reached **through LiteLLM 1.103.0**
**Chain validated:** `Pipeline → LLMClient Protocol → ProviderRouter → LiteLLMBackend → LiteLLM → Gemini`
**Verdict:** **The first real LiteLLM-backed request succeeded.** LiteLLM is functional as a
routing layer for Gemini. Two production defects were found and fixed during validation.
Several objectives could not be completed because the Gemini free tier's per-model daily
allowance (20 requests/model/day) was exhausted partway through the run. Every gap is
stated explicitly below rather than reported as a pass.

---

## 1. What passed

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Router constructed from config | **PASS** | `backend=litellm` |
| 2 | Router satisfies the `LLMClient` Protocol | **PASS** | `isinstance(client, LLMClient)` |
| 3 | Stages receive the Protocol, not an SDK client | **PASS** | `type(client).__name__ == "ProviderRouter"` |
| 4 | **Real request Pipeline → LiteLLM → Gemini** | **PASS** | `gemini-2.5-flash` → `'ok'` in 7.7 s |
| 5 | Streaming delivers multiple real chunks | **PASS** | 6 chunks, 1489 chars, via `gemini-2.5-flash` |
| 6 | Stream usage metered (was 0 before the fix) | **PASS** | `in=13 out=48 status=ok` |
| 7 | Real embedding returned | **PASS** | 3072 dims, `embedder.dimensions == 3072` |
| 8 | Dimensionality reported matches the vector | **PASS** | 3072 == 3072 |
| 9 | Real cosine similarity | **PASS** | `cosine(GAT, GCN) = 0.7963`, in range |
| 10 | Dimension mismatch raises | **PASS** | `EmbeddingDimensionMismatch` |
| 11 | Embedding cache hit, no second call | **PASS** | `hits=1` |
| 12 | Cache prevents duplicate provider calls | **PASS** | first 3.76 s → cached 0.0000 s |
| 13 | Cache hit returns no provider response | **PASS** | `resp2 is None` |
| 14 | LiteLLM retries disabled; RLA owns retry | **PASS** | `num_retries=0` |
| 15 | Rate limiter is a process-global singleton | **PASS** | identity check |
| 16 | LiteLLM stays optional (direct path never imports it) | **PASS** | `litellm in sys.modules == False` on the `gemini` path |
| 17 | All 4 schemas: `json_schema` sent verbatim, `strict=True` | **PASS** | mocked transport, schema compared field-for-field |
| 18 | Incapable model refused for a structured stage | **PASS** | `ProviderUnsupported` |
| 19 | Tokens read from the LiteLLM usage block | **PASS** | `in=31 out=17 status=ok` |
| 20 | Absent usage → `unknown`, never `0` | **PASS** | `status=unknown_usage` |
| 21 | FALLBACK on timeout / 429 / 5xx / network | **PASS** | tried `[flash-lite, flash]` in all four |
| 22 | NO FALLBACK on auth / invalid-request / unsupported / schema / programming error | **PASS** | tried exactly `[flash-lite]` in all five |
| 23 | NO FALLBACK on daily quota by default | **PASS** | tried `[flash-lite]`; error names the opt-in |
| 24 | FALLBACK on quota when opted in | **PASS** | tried `[flash-lite, flash]` |
| 25 | Full suite green after the fixes | **PASS** | **492 passed**, ruff clean |

**Live structural-output result (objective 4), partial — see §4.** Two of four schemas
completed live through LiteLLM on `gemini-2.5-flash`:

| Schema | Model | Result |
|---|---|---|
| `QuerySet` | `gemini/gemini-2.5-flash` | **PASS** — 4 queries returned, validated |
| `ScoreSet` | `gemini/gemini-2.5-flash` | **PASS** — p1 scored 5, validated |
| `PaperFacts` | `gemini/gemini-2.5-flash` | **NOT REACHED** — daily quota exhausted |
| `Verdict` | `gemini/gemini-2.5-flash` | **NOT REACHED** — daily quota exhausted |

Earlier in the same day, **all four schemas validated live** against the direct Gemini
backend on `gemini-2.5-flash` (3/3 on flash, 1/1 on flash-lite). The LiteLLM path has
therefore been shown to produce schema-valid output for two of the four, and the request
construction is verified identical for all four.

## 2. What failed

Two genuine defects, both found by this validation and **both fixed**.

### 2.1 `build_backend` discarded the caller's cache and cost tracker — FIXED

`build_client(settings, cache, tracker)` accepted both, but `build_backend` was called
with `settings` alone, so `LiteLLMBackend` constructed its **own empty `CostTracker`**.
Consequence: on the LiteLLM path the run's cost report read `calls=0, tokens=0,
estimated_usd=0.0, cost_status="ok"` — a confident, wrong `$0.00`, which is precisely
the silent-zero defect this migration was built to eliminate. The direct Gemini path was
unaffected because it did not go through the factory.

Fixed in `src/rla/llm/factory.py:27-49`; `cache` and `tracker` are now threaded through.
Confirmed by re-running the usage check.

### 2.2 An experiment that misread the daily-quota signal — REVERTED

Live errors read `quota exhausted ... Please retry in 38.4s`, which looked like a
per-minute bucket rather than a daily cap. I changed the classifier to let a short retry
window override the `perday` marker.

**This was wrong and has been reverted.** The repository's own captured fixture
(`tests/test_p2_quota.py:29-39`) is a real per-day 429 body that contains *both*
`quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'` **and**
`Please retry in 38.4s`. The retry hint is therefore not evidence of a burst bucket.
The change made three existing tests fail and would have turned every daily-cap failure
into three pointless retries before the same terminal error. The original marker-based
heuristic is correct and stands.

Recorded because the incorrect reasoning is instructive: a short "retry in Ns" string
alongside a per-day quota is normal provider behaviour, not a contradiction.

## 3. What could not be verified (and why)

**Blocker: the Gemini free tier allows 20 requests per model per day.** Both configured
models were exhausted during this session:

```
gemini-2.5-flash-lite -> 429 RESOURCE_EXHAUSTED, quota exhausted
gemini-2.5-flash      -> succeeded initially, then 429 quota exhausted
```

Not re-checkable until the daily reset. Consequently:

| Objective | Status | Why |
|---|---|---|
| 4. All four schemas live via LiteLLM | **PARTIAL** (2/4) | `PaperFacts`, `Verdict` blocked by quota. Request construction verified for all four. |
| 5. Real streaming | **PASS** | 6 real chunks, usage metered. |
| 6. Real embeddings + dimensionality | **PASS** | 3072 dims, mismatch raises. |
| 7. Normalized usage accounting | **PASS** | Live stream metering + mocked text path. |
| 8. Cache prevents duplicate calls | **PASS** | Real, 3.76 s → 0.0000 s. |
| 9. RLA is the single retry owner | **PASS** | `num_retries=0` observed on a real call. |
| 10. Fallback on transient failures | **PASS (simulated)** | 4 fault classes, real LiteLLM backend underneath. |
| 11. No fallback on terminal errors | **PASS (simulated)** | 5 error classes. |

**Not claimed:** a live end-to-end failover, where a real provider fault causes a real
request to succeed on a second model. The fault injection is simulated; only the fallback
*logic* is verified, not the provider's behaviour under a real outage.

## 4. Two model-routing observations

**Per-model quota is real and per-model.** With `flash-lite` exhausted, `flash` still
served requests — exactly the condition ADR-004 describes. This is the first concrete
evidence that the fallback chain is a genuine capability rather than a theoretical one.

**Both schemas that ran live returned semantically correct output**, not merely
schema-valid output: `QuerySet` produced four on-topic sub-area queries; `ScoreSet` scored
the graph-attention paper 5 and the coral-reef paper low. The self-correcting retry loop
never fired, so schema-constrained decoding did the work.

## 5. Verification method

| Objective | Method |
|---|---|
| 1, 3, 5, 6, 8, 9 | **Live** — real requests to Gemini via LiteLLM |
| 4 (2 of 4) | **Live** |
| 4 (request shape), 7, 10, 11 | **Mocked transport** — real backend code against a fake `litellm` module |
| 16, 25 | **Static** — suite and AST checks |

Mocked checks prove *our* behaviour. They cannot prove provider compatibility. The two are
not conflated anywhere in this report.

## 6. Remaining risks

1. **The free tier cannot run this pipeline.** 20 requests/model/day against a corpus
   needing ~100 extraction calls. A real run requires a paid key. This is a
   pre-existing constraint, not a migration defect, but it makes live validation of the
   full pipeline impractical.
2. **Two of four schemas are unvalidated through LiteLLM specifically.** `PaperFacts` is
   the most complex schema and is the one extraction depends on. It validated live
   through the direct backend; the LiteLLM path is verified only at the request level.
3. **Fallback has never fired against a real outage.** The logic is tested; the provider
   interaction is not.
4. **The quota misclassification remains fragile.** It is a message-marker heuristic
   because no provider exposes a structured quota-period field. A provider change could
   silently reclassify a daily cap as retryable. Worth revisiting if a second provider is
   added.
5. **LiteLLM is fast-moving.** 1.103.0 is pinned `<2`. It brings 16 transitive deps
   including `boto3`, `tiktoken`, and `openai`, and its exceptions subclass `openai.*`.
6. **A cache hit reports unknown usage.** Correct in principle, but it means a
   fully-cached run legitimately shows `unknown` rather than `$0.00`.
7. **`RLA_STRUCTURED_MODEL=gemini-2.5-flash` was required** to complete validation,
   because the default `flash-lite` had no quota left.

## 7. Reproduction

```powershell
# one real request, current provider
.\.venv\Scripts\python.exe -m rla.cli doctor --llm

# or, with the router under test
$env:RLA_LLM_PROVIDER="litellm"
$env:RLA_STRUCTURED_MODEL="gemini-2.5-flash"
.\.venv\Scripts\python.exe -m rla.cli doctor --llm
```

Suite: `.\.venv\Scripts\python.exe -m pytest tests/ -q` → **492 passed**.
Lint: `.\.venv\Scripts\python.exe -m ruff check src/ tests/` → clean.

## 8. Claim boundary

**Supported by this report:** LiteLLM 1.103.0 successfully routed at least one real
request to Gemini and returned correct output, including schema-constrained structured
output for two of the four production schemas, real streaming with token accounting, and
real embeddings with dimensionality reporting. The `LLMClient` Protocol remains the sole
application seam; no pipeline module imports LiteLLM or any provider SDK, and the direct
Gemini backend still works with LiteLLM uninstalled.

**Not supported:** that the full pipeline completes end-to-end on a free-tier key; that
`PaperFacts` and `Verdict` validate live through LiteLLM; that provider failover works
against a real outage; or that any second provider works at all — no second provider is
configured, and none was added.
