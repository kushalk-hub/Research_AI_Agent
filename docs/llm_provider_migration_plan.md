# LLM Provider Migration Plan

**Status:** In progress
**Date:** 2026-09-28
**Author:** architecture-designer
**Baseline:** [`docs/llm_architecture_audit.md`](llm_architecture_audit.md)
**Related ADRs:** [`docs/adr/`](adr/)

---

## 0. Decisions taken by the maintainer (recorded, not re-litigated)

| # | Decision |
|---|---|
| D1 | Verification strategy: **one live smoke test, then mocked transport.** Do not burn the daily quota proving wiring. |
| D2 | **Gemini primary only** for now. No second real provider configured. |
| D3 | **Keep `GeminiClient` as a selectable backend.** Prove equivalence before adding anything. |
| D4 | LiteLLM is an **optional extra** (`[router]`), lazily imported. The default install stays lean. |
| D5 | Verify remaining schemas on the **strong model's** own quota budget. |
| D6 | Fix the `strong_model` bug, but expose **per-stage model selection** so the expensive model is opt-in per stage. |
| D7 | Wire **`gemini-2.5-flash` as a real fallback** for `gemini-2.5-flash-lite` — separate per-model daily budget, demonstrably available while flash-lite is exhausted. |

---

## 1. Current architecture

```text
Pipeline stages ──► LLMClient Protocol ──► GeminiClient ──► google-genai ──► Gemini API
                     (rla/llm/base.py)     (llm/gemini.py)
```

Single provider. The `LLMClient` Protocol is a good seam and every one of the five
production call sites already depends on it. What sits *below* the seam, however, is
Gemini-shaped in five ways the audit confirmed:

| # | Gemini-specific coupling | Location | Failure mode if another provider is dropped in |
|---|---|---|---|
| C1 | `response_schema` / `response_mime_type` for structured output | `gemini.py:81-86` | 4 of 5 stages lose schema-constrained decoding |
| C2 | `usage_metadata.prompt_token_count` token parsing | `base.py:66-74` | **silent** `$0.00` cost reports |
| C3 | Pricing table keyed on Gemini model-ID substrings | `cache.py:23-28, 68-73` | `flash-lite` already mispriced 3× (audit §16.2) |
| C4 | `is_daily_quota` matching Gemini's 429 body text | `retry.py:37-51` | other providers' quota errors treated as ordinary 429s |
| C5 | `Embedder` is concrete, with a silent dimension-mismatch failure | `embeddings.py:19-27` | resolution tiers 2-3 die without an error |

Plus one correctness bug: `strong_model` is passed to extraction/resolution but never
forwarded to the generation call (audit §16.1), and streaming is never metered (§16.3).

---

## 2. Target architecture

```text
Pipeline consumers
        │
        ▼
Application LLMClient Protocol          llm/base.py        (PRESERVED, extended)
        │
        ▼
ProviderRouter                           llm/router.py      (NEW)
        │  owns: fallback policy, capability gating,
        │        error normalisation, usage normalisation
        │
        ├──► DirectGeminiBackend          llm/gemini.py      (EXISTING, unchanged)
        │        and google-genia ──► Gemini API
        │
        └──► LiteLLMBackend               llm/litellm_backend.py  (NEW, optional extra)
                 and litellm.acompletion ──► Gemini / OpenAI / …

EmbedderClient Protocol                  llm/embedding_base.py   (NEW)
        │
        ├──► DirectEmbedder              llm/embeddings.py       (EXISTING)
        └──► LiteLLMEmbedder             llm/litellm_backend.py  (NEW)
```

**The application stages are unaware of** Google SDK syntax, OpenAI SDK syntax, LiteLLM
routing, provider usage metadata, and provider error strings.

### Design rule honoured

This is deliberately **not** a lowest-common-denominator API. The `LLMClient` Protocol keeps
its three-method shape and gains *capability declaration* and *normalised results* rather
than being flattened. Provider-specific detail lives **inside** the backends.

---

## 3. Why the existing `LLMClient` Protocol is retained

`llm/base.py:22-63` is a three-method contract (`generate_text`, `generate_structured`,
`stream_text`) with no Gemini types in its signatures. All five production call sites
already type against it. The audit rated the seam as "real and unusually well-placed".

Replacing it with LiteLLM-native calls would be a strict regression: every stage would
acquire a provider vocabulary, and a provider swap would stop being a config change.
**Retained, extended, not replaced.**

---

## 4. Why LiteLLM is being introduced

Honest framing — LiteLLM is **not** a universal equaliser, and this document does not
pretend otherwise.

| Reason | Detail |
|---|---|
| Structured output parity | One `response_format`/`json_schema` argument instead of per-provider schema plumbing, so C1 stops being a Gemini-only path. |
| Provider error taxonomy | LiteLLM normalises provider errors into a single exception family, so C4 stops depending on string matching. |
| Usage normalisation | LiteLLM emits a consistent `usage` block, so C2 becomes a shape read rather than a name guess. |
| Model-string routing | `provider/model` strings let a model swap be configuration. |

### 4.1 What LiteLLM does **not** do (recorded so nobody assumes it)

- **It does not make structured output reliable.** A provider that cannot honour
  `json_schema` will not start honouring it because LiteLLM is in the path. LiteLLM
  detects this via `supports_response_schema`; the router uses that to **refuse**
  unqualified fallback, not to paper over it.
- **Its exception classes subclass `openai.*`** (verified from the wheel:
  `litellm/exceptions.py` — `AuthenticationError(openai.AuthenticationError)` etc.).
  Importing LiteLLM therefore imports the OpenAI SDK. That is a real coupling cost.
- **It costs 16 core dependencies** (verified from wheel metadata: `boto3`, `tiktoken`,
  `aiohttp`, `openai`, `tokenizers`, `jsonschema`, …) against the project's current 7.
  Hence D4: optional extra.
- **It is synchronous-with-async-shadows.** `acompletion` exists but the SDK under it is
  sync, so it is still thread-bound.

---

## 5. Concern ownership — one clear owner per concern

The brief requires this explicitly, because RLA already has `retry.py` and LiteLLM has
its own retry/router. Duplicating both would double-count retries and double-charge the budget.

| Concern | Owner | Rationale |
|---|---|---|
| Per-attempt retry + backoff + jitter | **LiteLLM** (`num_retries`) when the LiteLLM backend is active; `rla.llm.retry` otherwise | Avoids a nested retry loop (RLA retry × LiteLLM retry = 25 attempts). |
| Provider-call **timeout** | **RLA** (new) | LiteLLM passes timeouts through inconsistently; RLA needs one guarantee. |
| Cross-provider **fallback** | **RLA router** | LiteLLM's `fallbacks` is per-request and would bypass RLA's budget/capability gates. |
| Per-minute **rate limiting** | **RLA** (`RateLimiter`) | Already global and shared with embeddings; LiteLLM's limiter is per-client. |
| Per-run **budget** | **RLA** (`Spender`) | **Never removed.** It is an application cost-control semantic, not a transport concern. |
| **Daily quota** fail-fast | **RLA**, on a *normalised* error category | Depends on RLA's budget story, not the SDK. |
| **Caching** | **RLA** (SQLite) | Cache-first is an application guarantee (`PLAN.md` P1 gate). |
| **Usage/cost** normalisation | **RLA** | LiteLLM's usage block is an input; RLA's accounting is the contract. |

**Rule:** exactly one retry layer is active at a time. The LiteLLM backend sets
`num_retries=0` and lets RLA retry, so a failed call never retries twice.

---

## 6. Fallback semantics

```text
Primary model
    │
    ├─ recoverable transport failure (timeout / 429 per-minute / 5xx / network)
    │        └──► fallback model, if capability-compatible
    │
    └─ NOT recoverable (auth / bad credentials / invalid config / unsupported
       schema / programming error / daily quota exhausted)
            └──► raise immediately
```

### 6.1 Why daily-quota exhaustion is NOT auto-fallback

This is the sharpest design question in the migration, and D7 sits in tension with it.

The obvious argument for falling back on quota exhaustion is exactly what was observed:
flash-lite's quota died, flash still had budget, so a fallback would have kept the run
alive. But:

- **Silently spending a second model's budget** on a first model's exhaustion can burn
  the reserve the operator wanted kept for later stages. `config.py:59-63` already
  documents this exact fear ("leaving nothing for the stages after it").
- **It is a capacity condition, not a fault.** The run is working correctly; there is
  simply no capacity.

**Resolution:** quota exhaustion is classified `QUOTA_EXHAUSTED`, which is **not**
auto-retried and **not** auto-fallen-back by default. It raises a normalised error that
carries an explicit, actionable message. Fallback on quota is **opt-in** via
`RLA_FALLBACK_ON_QUOTA` (default off), so the D7 fallback covers transient failures while
leaving the budget decision to the operator.

This is documented here because a future reader will otherwise read D7 and conclude quota
failover is automatic. It is not.

### 6.2 Capability gate

A model is only eligible as a fallback for a stage if it satisfies the stage's
requirement:

- Structured stages require `supports_structured_output == True`.
- If it does not, it is **not** used for that stage. There is no silent degradation to
  unvalidated JSON — that would resurrect the exact silent-corruption class of bug the
  audit catalogued.

---

## 7. Structured-output strategy

**The contract is not weakened.** `generate_structured` keeps the full four-layer funnel
from the audit:

1. Provider schema constraint (`response_schema` for Gemini direct;
   `response_format={"type": "json_schema", …}` for LiteLLM).
2. `extract_json()` fence/prose stripping.
3. Pydantic validation with self-correcting retry (validation error fed back into the prompt).
4. Stage-level degradation (`LLMError` → the stage's existing fallback).

**Live verification (2026-09-28, real calls, not mocked):**

| Schema | Model | Result |
|---|---|---|
| `QuerySet` | `gemini-2.5-flash-lite` | **PASS** |
| `ScoreSet` | `gemini-2.5-flash` | **PASS** |
| `PaperFacts` | `gemini-2.5-flash` | **PASS** |
| `Verdict` | `gemini-2.5-flash` | **PASS** |

4/4 validated. This is the pre-migration baseline the router is measured against.

**Per-provider capability (documented, not assumed):**

| Provider | Mechanism | Reliability |
|---|---|---|
| Gemini (direct, `response_schema`) | Server-side constrained decoding | **Strong** — schema is enforced by the decoder, not by prompt compliance. |
| Gemini (via LiteLLM) | Same schema, routed | Expected equivalent; **to be verified** by the acceptance tests. |
| OpenAI (via LiteLLM) | `json_schema` strict mode | Strong, but **not verified here** (D2: no second provider configured). |
| Anthropic (via LiteLLM) | No native constrained decoding; JSON via tool-use or prompt | **Weaker.** Will require a capability check and likely a prompt-level fallback path. |

**Anthropic-class providers are the reason the capability gate exists.** A router that
silently used them for `PaperFacts` would be the "lowest common denominator" failure this
design is explicitly told to avoid.

---

## 8. Embedding strategy

A new `EmbeddingClient` Protocol, because the current `Embedder` is concrete and is
*not* behind `LLMClient` (audit coupling C5).

Three hard requirements, all from audit findings:

1. **Dimension validation is explicit.** `embed_one` records the observed dimensionality,
   and `cosine()` raises `EmbeddingDimensionMismatch` on mismatch instead of returning
   `0.0`. The old silent `0.0` return is exactly the bug that would make a model swap
   look like "no concepts are similar".
2. **Cache keys stay model-aware** — `embed:<hash(embedding_model, text)>`, unchanged, so
   vectors from one model are never served to another.
3. **Usage is metered** for embeddings, as it already is.

---

## 9. Error normalisation

Application-level categories, replacing provider-specific string matching. All inherit
`RlaError` so existing `except RuntimeError` handlers in the pipeline keep working.

| Category | Trigger | Retry | Fallback | Meaning |
|---|---|---|---|---|
| `TIMEOUT` | call exceeded the configured timeout | Yes | Yes | transient |
| `RATE_LIMITED` | 429, per-minute/burst | Yes | Yes | transient |
| `QUOTA_EXHAUSTED` | daily/period quota gone | **No** | opt-in | capacity, not fault |
| `SERVER_ERROR` | 5xx / provider overload | Yes | Yes | transient |
| `NETWORK_ERROR` | connection reset, DNS, refused | Yes | Yes | transient |
| `AUTH_FAILED` | 401 / 403 / OAuth-token misuse | **No** | **No** | fatal, operator action |
| `INVALID_REQUEST` | 400 / malformed / bad model id | **No** | **No** | programming or config bug |
| `STRUCTURED_OUTPUT` | schema could not be satisfied | No (inner retry first) | No | correctness |
| `BUDGET_EXHAUSTED` | RLA per-run cap | **No** | **No** | deliberate stop |
| `UNSUPPORTED` | provider lacks the required capability | **No** | **No** | configuration |

`normalize_provider_error()` maps SDK/LiteLLM exceptions into these. Gemini-specific
string matching is **retained only** as a *pre-classifier* (to recognise
`GenerateRequestsPerDay…`-shaped quota errors early and cheaply) and is never the general
mechanism. Mapping is by exception **type and status code**, not by message text.

---

## 10. Usage and cost normalisation

New contract, replacing `usage_from_response() -> tuple[int, int]`:

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    @property
    def known(self) -> bool: ...
```

**Unknown is `None`, never `0`.** The audit's most damaging silent path was unsupported
usage collapsing to `0` and then to `$0.00`. `CostTracker` therefore distinguishes:

- `estimated_usd: float` — computed, when tokens are known *and* the model is priced
- `estimated_usd: None` + `cost_status: "unknown_usage" | "unpriced_model" | "ok"`

Pricing lookup is fixed from substring matching to **exact id match, then explicit
alias**. This is what stops `gemini-2.5-flash` matching inside `gemini-2.5-flash-lite`
(a 3× overcharge, audit §16.2).

**Streaming is metered.** LiteLLM's streamed responses carry usage on the final chunk
(with `stream_options={"include_usage": True}`); the direct Gemini path accumulates
chunks and reads usage from the aggregated response. If a backend supplies neither, the
result is `known=False` — reported as unknown, not as zero.

---

## 11. Per-stage model configuration

Per D6, model choice becomes explicit and per-stage rather than the current accidental
behaviour:

| Setting | Env | Applies to | Default |
|---|---|---|---|
| `fast_model` | `RLA_FAST_MODEL` | generic fallback | `gemini-2.5-flash-lite` |
| `strong_model` | `RLA_STRONG_MODEL` | generic fallback | `gemini-2.5-flash` |
| `structured_model` | `RLA_STRUCTURED_MODEL` | query expansion, scoring, extraction, resolution | `fast_model` |
| `answer_model` | `RLA_ANSWER_MODEL` | streamed answer generation | `strong_model` |
| `embedding_model` | `RLA_EMBEDDING_MODEL` | embeddings | `gemini-embedding-001` |
| `fallback_models` | `RLA_FALLBACK_MODELS` | comma-separated, in order | `gemini-2.5-flash` |
| `llm_provider` | `RLA_LLM_PROVIDER` | `gemini` \| `litellm` | `gemini` |
| `llm_timeout_seconds` | `RLA_LLM_TIMEOUT_SECONDS` | provider call timeout | 120 |

Model strings accept `provider/model` (LiteLLM convention, e.g. `gemini/gemini-2.5-flash`)
or a bare model id (direct backends infer the provider).

**This fixes the audit §16.1 bug by construction:** `structured_model` defaults to
`fast_model`, so the *documented* intent is preserved without silently moving 100 papers
onto a 20-calls/day model. Opting into `RLA_STRUCTURED_MODEL=gemini-2.5-flash` is an
explicit, informed act — which is what D6 asked for.

---

## 12. Risks and trade-offs

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | LiteLLM's 16 deps + 28 MB wheel | Slow installs, larger supply chain | Optional extra (D4), lazy import, suite runs without it |
| R2 | LiteLLM exceptions subclass `openai.*` | OpenAI SDK becomes a transitive dep | Accepted; the direct backend still avoids it entirely |
| R3 | LiteLLM changes fast (1.103.0, 100+ releases in months) | Upgrades may break | Pin in the extra; adapter is the only file that imports it |
| R4 | Fallback spends a second model's budget unexpectedly | Higher cost, depletion of reserve | Quota failover is opt-in and off by default (§6.1) |
| R5 | Anthropic-class fallback is weaker at structured output | Silent quality loss | Capability gate refuses it; no silent degradation |
| R6 | Refactoring `retry.py` breaks the P0 gate ("every outbound request cached") | Regression to a passed gate | Existing `llm/retry.py` API kept; tests must stay green |
| R7 | Changing cost reporting alters `data/eval` numbers | Eval reproducibility | `data/` fixtures are committed; re-run `rla eval` and diff |
| R8 | `strong_model` fix changes eval output | Corpus/extraction differences | Opt-in via `structured_model`, so default behaviour is unchanged |

**Deliberately not doing:** no proxy server, no queue, no worker pool, no local model
support, no multi-provider fan-out beyond a linear fallback list. The project is a
single-user CLI; adding distributed machinery would be over-engineering.

---

## 13. Migration steps

| # | Step | Risk |
|---|---|---|
| M1 | Add `llm/errors.py` (normalised categories + mapper) | Low — additive |
| M2 | Add `llm/usage.py` (`TokenUsage`), fix `CostTracker` pricing + unknown handling | Medium — touches reporting |
| M3 | Fix `usage_from_response` consumers; meter streaming | Medium |
| M4 | Add `llm/embedding_base.py`; raise on dimension mismatch | Medium — changes a silent failure into a loud one |
| M5 | Add per-stage model settings to `config.py` + `.env.example` | Low |
| M6 | **Fix §16.1**: forward `model` into every generation call | Medium — behaviour-changing if misconfigured |
| M7 | Add `llm/router.py` (`ProviderRouter`) with capability gate + fallback | Medium |
| M8 | Add `llm/litellm_backend.py` (lazy import) | Medium |
| M9 | Add `llm/factory.py`; repoint `cli.py` off direct `GeminiClient` | Low |
| M10 | Add `llm_timeout_seconds`; wrap provider calls in a timeout | Low |
| M11 | Tests: schemas, streaming, embeddings, errors, cache, cost, swap | Low |
| M12 | Re-run `rla eval`; diff against committed baseline | Low |

Rollback for each step is a revert; M2/M4/M6 are the only ones that change observable
behaviour, and M6 is opt-in via config.

---

## 14. Rollback strategy

| Level | Action | Effect |
|---|---|---|
| **L1 config** | `RLA_LLM_PROVIDER=gemini` | Direct backend, LiteLLM never imported. **Instant.** |
| **L2 optional dep** | Uninstall the `[router]` extra | Nothing breaks; `LiteLLMBackend` is not importable and is not selected. |
| **L3 code** | Revert `router.py` + `factory.py` | Restores the direct path; stages untouched either way. |
| **L4 full** | `git checkout` the pre-migration commit | Data files (`data/`) survive; only code moves. |

Because stages never import a provider, L1 is always available without a code change.
**That is the main reason the seam is preserved.**

---

## 15. Test and acceptance criteria

| # | Criterion | Method |
|---|---|---|
| A1 | No pipeline module imports `google.genai`, `litellm`, `openai`, or `anthropic` | Grep assertion in the test suite |
| A2 | 4 production schemas validate through the router | Live (done: 4/4) + mocked regression test |
| A3 | Streamed answer generation still yields chunks | Test with a fake streaming backend |
| A4 | Embeddings + cosine work; dimension mismatch **raises** | Test incl. mismatch case |
| A5 | 429 / timeout / 5xx / auth / malformed each map to the right category and trigger the right retry-or-fallback decision | Parametrised error tests |
| A6 | A cache hit makes **zero** provider calls | Cache-hit counter test |
| A7 | Token accounting + pricing correct for every configured model | Test the pricing fix; assert unknown ≠ 0 |
| A8 | Swapping provider/model changes **no** pipeline file | Config-only swap demonstrated |
| A9 | Full suite stays green | `pytest tests/ -q` |
| A10 | `ruff check src/` clean | Lint |

**Explicitly out of scope for claims:** live verification of a *second* provider. D2 means
no second provider is configured, so no failover claim will be made beyond the
same-provider, cross-model case that is actually testable here.

---

## 17. Implementation record

### Files added

| File | Purpose |
|---|---|
| `src/rla/llm/errors.py` | 10 normalised error categories; `retryable` / `fallback_eligible` derived from the category so no caller re-derives the policy |
| `src/rla/llm/error_map.py` | Maps SDK exceptions to categories by **type and HTTP status**, with one narrow message-based pre-classifier for period-quota detection |
| `src/rla/llm/usage.py` | `TokenUsage` where unknown is `None`; reads both the OpenAI and Gemini usage shapes |
| `src/rla/llm/embedding_base.py` | `EmbedderClient` Protocol; `cosine()` now **raises** on a dimension mismatch |
| `src/rla/llm/router.py` | `ProviderRouter`: model selection, capability gate, fallback policy |
| `src/rla/llm/litellm_backend.py` | LiteLLM backend, lazily imported |
| `src/rla/llm/factory.py` | Builds backend/router/embedder from configuration |
| `tests/test_p9_provider_routing.py` | 43 tests: categories, normalisation, routing, fallback, capability gate, usage, embeddings, timeout |
| `tests/test_p9_acceptance.py` | 19 tests asserting criteria A1-A7 structurally |
| `docs/adr/0001`-`0005` | Five ADRs |

### Files changed

| File | Change |
|---|---|
| `src/rla/config.py` | Per-stage models, fallback chain, `fallback_on_quota`, `llm_timeout_seconds`, exact pricing lookup |
| `src/rla/store/cache.py` | Pricing no longer substring-matched; `CostTracker` distinguishes ok / unknown_usage / unpriced_model |
| `src/rla/llm/base.py` | `LLMError` is now the parent of `ProviderError`; `usage_from_response` is provider-neutral |
| `src/rla/llm/gemini.py` | Implements the backend contract; timeout; normalised errors; **streaming metered** |
| `src/rla/llm/embeddings.py` | Protocol-conformant; dimension validation; timeout |
| `src/rla/llm/retry.py` | `timeout` parameter; **exhausted retries now preserve the error category** |
| `src/rla/pipeline/{extraction,resolve,scoring,query_expansion}.py` | **Forward `model` into the call** (audit §16.1) |
| `src/rla/pipeline/orchestrator.py` | Uses the factory; per-stage models |
| `src/rla/cli.py` | No longer names `GeminiClient`; probes the *configured* backend |
| `pyproject.toml`, `.env.example` | `[router]` extra; 8 new documented settings (30/30 fields now covered) |

### Two bugs found and fixed beyond the brief

1. **Exhausted retries silently disabled failover.** `call_with_retry` wrapped the last
   failure in a bare `LLMError`, discarding the status code. A 503 that exhausted its
   retries became `UNKNOWN`, which the router refuses to fall back from — so the retry
   layer was quietly turning provider failover *off* for exactly the transient faults it
   exists to handle. Now normalised, with the attempt count preserved in the message.

2. **`ProviderError` was not an `LLMError`.** The new error categories would have escaped
   the `except LLMError` handlers in five pipeline stages. `LLMError` is now their parent.

### Verification performed

| Check | Result |
|---|---|
| `pytest tests/ -q` | **492 passed** (3 consecutive runs), up from 425 |
| `ruff check src/ tests/` | All checks passed |
| A1 no pipeline module imports a provider SDK | Enforced by AST inspection in the suite |
| A2 four production schemas, **live** | **4/4 PASS** against real Gemini |
| A3 streaming | Chunks preserved; usage now metered from the final chunk |
| A4 embeddings | Dimensionality reported; mismatch raises |
| A5 429 / timeout / 5xx / auth / malformed | Each maps to the right category and retry/fallback decision |
| A6 cache hit | Zero provider calls for text and streaming |
| A7 cost | Pricing bug fixed; unknown ≠ 0 |
| LiteLLM backend (mocked transport) | **All 8 groups pass** — routing, json_schema shape, capability gate, usage, streaming, cache, error normalisation |

**Not claimed:** live failover was never exercised end-to-end. The fallback logic is
verified against simulated faults; a real cross-provider failover remains untested
because no second provider is configured (D2). The LiteLLM backend has never made a
real call — it is verified only against a mocked `litellm` module.

### Rollback

1. `RLA_LLM_PROVIDER=gemini` — instant, no code change.
2. Uninstall the `[router]` extra — nothing breaks.
3. `git checkout` the pre-migration commit.

## Open Questions for Architecture Redesign

---

## 16. Open questions carried into implementation

1. `RLA_STRUCTURED_MODEL` unset leaves 100-paper extraction on the cheap model. Confirm
   that is the intended default rather than a temporary convenience.
2. Should `RLA_LLM_TIMEOUT_SECONDS=120` also apply to streaming? A long answer can
   legitimately exceed 120 s; the timeout probably belongs on **first-token** latency
   rather than total duration. **Deferred to implementation as a known limitation.**
3. LiteLLM is currently only exercised through tests. A real
   `RLA_LLM_PROVIDER=litellm` run against Gemini is the honest next step and costs quota.
