# P12 — Multi-provider dispatch (Ollama, Gemini, OpenRouter)

**Date:** 2026-10-02
**Status:** design approved, not yet implemented
**Milestone:** P12 (split into P12a and P12b)

---

## 1. Context and problem

The Gemini free tier on this project allows **20 requests per day, per project, per model**
(measured live: `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: '20'`).
A 30-paper corpus needs 30 extraction calls, so it cannot complete in one day on a Gemini model
however well the code behaves. This is arithmetic, not a defect.

Ollama 0.20.7 is available on `localhost:11434` with `qwen3:4b`, and local inference is
unlimited. Measured on this machine:

| route | prompt tokens | per paper |
|---|---|---|
| Ollama native `/api/generate`, schema as grammar | 662 | **5.4 – 8.1s** |
| LiteLLM → Ollama `/v1/chat/completions`, `json_schema` | 4096 | 85 – 98s |

The 12x difference is not the model. Ollama's OpenAI-compatible route implements structured output
by **prepending ~3.4k tokens of format instructions to the prompt**; its native route uses real
grammar constraints and does the identical work with a 662-token prompt. Both were verified to
produce valid, schema-conformant `PaperFacts` extractions.

Four defects found and fixed during diagnosis (already merged, tests pinned) made the quota problem
considerably worse and are the reason the current routing layer is not trusted to scale further:

1. relevance scoring ran over the whole candidate pool (291 papers scored to keep 30);
2. the quota category was lost between the retry layer and the router, so
   `RLA_FALLBACK_ON_QUOTA=1` could never fire;
3. the orchestrator pinned `strong_model`, so `RLA_STRUCTURED_MODEL` never reached extraction;
4. the capability gate refused self-hosted models outright.

### What exists today

`ProviderRouter` is the single owner of model selection, capability gating, retry/fallback
eligibility and fallback order. It holds **one** backend. `RLA_LLM_PROVIDER` chooses between
`gemini` (native SDK) and `litellm` (everything else). That is why a native Ollama backend cannot
simply be added: there is nowhere to put it that a single-backend router can reach.

## 2. Goals

- One pipeline run may use **Ollama for the high-volume structured stages**, **Gemini for answer
  generation**, and **OpenRouter as fallback**, simultaneously.
- A native Ollama text backend using grammar-constrained structured output.
- Local embeddings, so the whole pipeline can run with zero Gemini dependency.
- Per-stage model overrides from the CLI and from a live TUI selector, both transient.
- The active model, provider and fallback decisions visible at all times.
- Switching embedding model must never reuse another embedding space's merge thresholds.

## 3. Non-goals

- Replacing `ProviderRouter`. It remains the authority for precedence, capability, retry/fallback
  eligibility and ordering.
- Moving any routing policy into the orchestrator (ADR-001).
- Persisting CLI or TUI selections to `.env`.
- Vector stores. Embeddings stay cache-backed and recomputed per run.
- Any change to the TUI's layout, panels or visual design beyond the model selector and the
  routing status rows.
- Phase 2 full text, SerpApi, Neo4j. Unrelated.

---

## 4. Architecture

```
pipeline stage → LLMClient → ProviderRouter → MultiBackend ─┬→ GeminiClient    (native SDK)
                                       (unchanged)         ├→ LiteLLMBackend  (OpenRouter, OpenAI, …)
                                                          └→ OllamaBackend   (native /api)
```

`MultiBackend` is a **backend**, not a router. It implements `RoutingBackend` and answers
`supports()`, `generate_text()`, `generate_structured()` and `stream_text()` by resolving which
provider owns the model id it is handed.

`ProviderRouter` keeps every policy it owns today.

### 4.1 Why cross-provider fallback needs no router change

`ProviderRouter._dispatch` already iterates candidates and calls `run(model=candidate)`.
`MultiBackend` resolves the owner *per candidate*, so a chain of
`ollama/qwen3:4b → gemini/gemini-2.5-flash → openrouter/…` works by construction. No change to
fallback logic is required.

Retry stays inside each backend via `call_with_retry`, so ADR-003 (exactly one retry layer) holds.

### 4.2 One canonical identity

```
config / flag / CLI id
        ↓  canonical_model(model, settings)
  canonical id              e.g. ollama/qwen3:4b
        ↓
  ├─ provider resolution
  ├─ LLM cache key
  ├─ embedding cache key
  ├─ merge-threshold lookup
  └─ doctor / TUI display
```

**Invariant:** once canonicalized, downstream code never independently re-interprets the original
model string. One identity, resolved once. This prevents two subsystems from growing subtly
different provider-resolution rules — the class of defect that produced the Gemini-to-Ollama
misroute.

Because the LLM cache key is derived from the canonical id, `qwen3:4b` and `ollama/qwen3:4b` share
one cache entry rather than two.

### 4.3 Provider resolution

| model id | provider | note |
|---|---|---|
| `ollama/qwen3:4b` | ollama | explicit prefix is authoritative |
| `gemini/gemini-2.5-flash` | gemini | |
| `openrouter/ling-3.0-flash:free` | litellm | |
| `openai/gpt-4o-mini` | litellm | |
| `gemini-2.5-flash` | gemini | bare, but unambiguously names its provider |
| `gpt-4o-mini`, `claude-…` | litellm | bare, same rule |
| `qwen3:4b` | **error** | bare and ambiguous |
| `foo/bar` | **error** | unknown provider prefix |

The rule, stated generally:

> A **bare** model id is accepted only when ownership is unambiguous. An **explicit provider
> prefix** is required whenever ownership is ambiguous. Anything else is an error.

Errors are actionable, not descriptive:

```
Ambiguous model id 'qwen3:4b'.
Specify an explicit provider prefix:
  ollama/qwen3:4b
  or another supported provider/model id.
```

```
Unknown provider prefix 'foo' in model id 'foo/bar'.
Known providers: gemini, litellm, ollama.
```

Both raise **before any network request is made**.

`RLA_LLM_PROVIDER` remains the configured default for provider-agnostic calls and is preserved as a
whole-run debugging override: pinning every model id to bare, provider-native forms forces one
backend for the entire run.

### 4.4 Lazy backend construction

Backends are constructed on first use, so a Gemini-only configuration never imports or constructs
an Ollama or LiteLLM backend, and the `[router]` extra stays genuinely optional.

---

## 5. Model selection precedence

```
model_for(role):
    session = overrides.get(role)        # TUI / transient override
    if session is not None:
        return session
    if explicit is not None:
        return explicit
    configured = configured_role_model(role)
    return configured if configured else fast_model
```

Checked with `is not None`, never truthiness, so an empty string cannot silently win.

### 5.1 This is a deliberate change to an existing contract

The documented contract today is *"an explicit `model=` argument always wins"*. A session override
now sits **above** it. That is intentional: the TUI user must be able to say "use Ollama for
extraction in this run" even where a stage currently supplies a model explicitly (the orchestrator
does, to label the cost report).

So the contract becomes:

> A session override is a deliberate higher-priority user control and supersedes stage and call-site
> defaults for that role. Absent an override, an explicit `model=` argument still beats the stage
> role, exactly as before.

`test_an_explicit_model_argument_still_wins` is **retargeted, not deleted**: it continues to assert
that an explicit argument beats the stage role, and a new test asserts that a session override
beats an explicit argument. The docs (`docs/OPERATIONS_GUIDE.md` §3.3) are updated to match.

### 5.2 In-flight safety

`model_for` is evaluated once at dispatch. A switch applied mid-run therefore affects the next
eligible stage or request and cannot disturb a call that has already resolved its model. The
judge-pair ordering and `MAX_JUDGE_CALLS` budget are unaffected by a switch.

---

## 6. `OllamaBackend` (text)

`src/rla/llm/ollama_backend.py`, implementing `RoutingBackend`. Transport is `httpx` (already a
core dependency), executed through `call_with_retry` with the existing limiter, spender and
timeout.

| method | request | response |
|---|---|---|
| `generate_text` | `POST /api/generate` `{model, prompt, stream:false, think, options:{temperature}}` | `.response` |
| `generate_structured` | same, plus **`format: <json_schema>`** | `.response`, validated against the schema |
| `stream_text` | `stream:true` | NDJSON lines; yields `.response` per line |

`generate_structured` reuses the existing self-correction loop: on a validation failure the error
is appended to the prompt and the call is retried, exactly as `LiteLLMBackend` does.

### 6.1 `think: false` by default

The configured models are reasoning models. Free-form thinking interleaved with a grammar
constraint is asking for trouble, and measurement showed thinking costs essentially nothing here
(8.0s with, 7.7s without). `RLA_OLLAMA_THINK` exposes it for the answer stage if wanted.

### 6.2 Capability is reported by the backend, not inferred

`supports(model, "supports_structured_output")` answers `True` for non-embedding models, because
Ollama grammar-constrains any schema supplied via `format`. This was verified against the real
`PaperFacts` schema, which returned valid output with non-empty concepts.

A consequence worth stating: on this path `RLA_STRUCTURED_OUTPUT_MODELS` is **not needed**. It
remains supported for the LiteLLM route only, where LiteLLM's static table answers `False` for a
model it does not recognise — and answers inconsistently depending on what earlier code in the
process already touched.

Capability support is distinct from quality. Structured output being *supported* says nothing about
whether an *embedding* model's similarity thresholds are calibrated. Those are tracked separately
(§7.3).

### 6.3 Unknown model

Ollama returns `404 {"error":"model 'x' not found"}`, which normalizes to `INVALID_REQUEST`. An
actionable rewrite turns it into:

```
model 'ollama/qwen3:4b' not found on http://localhost:11434
  run: ollama pull qwen3:4b
```

---

## 7. Embedding providers

### 7.1 The abstraction

`embedding_base.py` gains an `EmbeddingProvider` protocol: `embed_one`, `embed_many`, `dimensions`,
`model_id`, `key(text)`.

```
EmbeddingProvider
├── Embedder (Gemini)     — unchanged behaviour
└── OllamaEmbedder        — POST /api/embed {model, input:[...]} → {embeddings: [[...]]}
```

`/api/embed` is **batched**: embedding 163 concept names is one request, not 163. This materially
changes operational behaviour for entity resolution, where the current graph produces 160+ names.

`build_embedder` selects by the same provider resolution: `ollama/nomic-embed-text` →
`OllamaEmbedder`, bare `gemini-embedding-001` → Gemini.

Verified on Ollama 0.20.7: `/api/embed` returns 768-dimensional vectors for `nomic-embed-text`, and
that version **auto-pulls a missing embedding model on demand**.

> **A fully local pipeline still needs `GEMINI_API_KEY` to be set.** `build_client` returns `None`
> without it, and the orchestrator treats a `None` client as degrade mode. P12b therefore changes
> `build_client`/`build_embedder` so that *any* usable provider is sufficient, rather than keying
> client construction on the Gemini credential specifically. Until that lands, keep the key set even
> when every call is local.

### 7.2 Vector identity

`Embedder._key()` already includes the model id, and
`test_a4_embedding_cache_keys_are_model_aware` pins it. There is no separate vector store, so
changing the embedding model simply misses every cache key and triggers re-embedding. P12b extends
this to canonical ids so the same model reached by two spellings shares one cache entry.

**Vectors from different embedding models are never compared.** The dimension guard in
`embedding_base.cosine` already raises `EmbeddingDimensionMismatch` on a mismatch; a model-aware
key ensures different models do not even reach the same comparison.

### 7.3 Merge thresholds are per embedding model

```python
EMBEDDING_THRESHOLDS: dict[str, MergeThresholds] = {
    "gemini/gemini-embedding-001": MergeThresholds(auto=0.92, maybe=0.70, calibrated=True),
}
```

Keyed by canonical id, so two providers exposing the same bare name cannot collide.

For a model with no entry:

- `auto = None` — **automatic merging is disabled entirely**;
- every candidate pair at or above the judge floor becomes eligible for the existing LLM-judge
  path, subject to the existing most-similar-first ordering and the `MAX_JUDGE_CALLS` budget of 40;
- the resolve stage emits a `warn` event:

```
merge thresholds are UNCALIBRATED for 'ollama/nomic-embed-text';
automatic merging is disabled and borderline pairs are going to the judge
```

**Safety direction is preserved.** With auto-merge off the system produces *more duplicates*, never
a fused lineage path. It does **not** mean every pair is judged: the floor and the budget still
apply, so model switching cannot become unbounded pairwise LLM spend.

The lifecycle:

```
new embedding model → embedding works → UNCALIBRATED → auto-merge OFF
  → judge handles candidates within budget
  → calibration pass → operator approval → calibrated → auto-merge ON
```

### 7.4 Calibration

A pass in `eval/` loads stored extractions, embeds with the active model, reports the similarity
distribution, and proposes thresholds at stated false-merge and judge-load targets. It **never
writes to `EMBEDDING_THRESHOLDS` without explicit operator approval** — the same honesty rule the
evaluation harness already follows for a metric it cannot measure.

Gemini keeps `auto = 0.92`, `maybe = 0.70`, unchanged. A future calibrated Nomic threshold may
legitimately differ; the calibration system is genuinely model-specific and no calibrated model
inherits another's numbers.

---

## 8. Surfaces

### 8.1 CLI

```
rla run --structured-model ollama/qwen3:4b --answer-model gemini/gemini-2.5-flash
rla tui --structured-model ollama/qwen3:4b --answer-model gemini/gemini-2.5-flash
```

Implemented as `Settings.model_copy(update=...)` before the `Pipeline` is constructed, so every
downstream reader sees the override. Nothing is written to `.env` — an experimental demo choice
must not become permanent configuration by accident.

### 8.2 TUI model selector

Operates on the **same** event stream and the same `Pipeline` as `rla run`; it introduces no
TUI-specific execution path, preserving the existing one-stream invariant.

The panel distinguishes three distinct states per role:

```
Extraction
  Configured : ollama/qwen3:4b
  Override   : —
  Resolved   : ollama/qwen3:4b
```

and after a switch:

```
Extraction
  Configured : ollama/qwen3:4b
  Override   : gemini/gemini-2.5-flash
  Resolved   : gemini/gemini-2.5-flash
```

That separation is what makes the routing auditable at a glance. Selections are session-scoped and
labelled as such.

### 8.3 Fallback observability

`ProviderRouter` gains an optional `on_fallback` callback. It **observes** fallback decisions and
owns none of them: eligibility, ordering and the retry/fallback split remain entirely inside
`ProviderRouter` and the backend's `call_with_retry`. The callback cannot become a second retry or
fallback mechanism, and it performs no I/O — it records `(stage, from, to, reason)` into
`PipelineState`.

`_build_pipeline()` returns the router so the TUI can register the handler. The CLI does not need
it: fallbacks already appear in the final `DONE` stats and in the actionable error text produced by
`_quota_hint` and `_CATEGORY_GUIDANCE`.

### 8.4 `doctor` and `stats`

| surface | content |
|---|---|
| `rla doctor` | live backends; resolved provider + model per role; embedding model marked **local / remote**; merge thresholds **calibrated / UNCALIBRATED** |
| `rla doctor --llm` | live probes, deduplicated (below) |
| `rla stats` | embedding model + calibration state alongside the corpus and graph tables. **No live probing** — `doctor` owns health, `stats` owns stored state |

#### The `doctor --llm` counting rule

```
resolve all required roles
        ↓
canonicalize
        ↓
deduplicate canonical model ids
        ↓
exactly one live probe per unique model
```

Given:

```
structured → ollama/qwen3:4b
extraction → ollama/qwen3:4b
resolution → ollama/qwen3:4b
answer     → gemini/gemini-2.5-flash
embedding  → ollama/nomic-embed-text
```

`qwen3:4b` is probed **once**, not three times. `doctor --llm` performs real, uncached requests, so
duplicates cost quota and time for no information.

**Embedding probes are counted separately from text-model probes.** `/api/embed` is a different
endpoint and a different capability, so an embedding probe is never satisfied by a text-model probe
and vice versa. An embedding model is reported in its own block.

Display:

```
OLLAMA
  ollama/qwen3:4b           ok
    roles: structured, extraction, resolution

GEMINI
  gemini/gemini-2.5-flash   ok
    roles: answer

EMBEDDING
  ollama/nomic-embed-text   ok   local
    thresholds: UNCALIBRATED (auto-merge disabled)
```

---

## 9. Testing

### 9.1 P12a — provider routing

| area | pinned behaviour |
|---|---|
| canonical identity | explicit prefixes resolve to their provider; bare `gemini-2.5-flash` → gemini, `gpt-*` / `claude-*` → litellm; **bare `qwen3:4b` raises the actionable error before any network request**; `foo/bar` raises naming the known providers; `canonical_model` is idempotent; a non-canonical input produces the **same cache key** as its canonical form |
| `MultiBackend` | `gemini/…` → Gemini, `ollama/…` → Ollama, `openrouter/…` → LiteLLM; unknown provider errors **without sending a request**; backends constructed **lazily**, so a Gemini-only config constructs neither Ollama nor LiteLLM; `supports()` delegates to the owning backend |
| A8 (rewrite) | dispatch behaviour instead of `isinstance(…, GeminiClient)`: the three providers above, plus default-provider resolution for provider-agnostic calls. Preserves the original intent — provider selection is configuration/model-driven, not hard-coded |
| **cross-provider** | structured → Ollama, answer → Gemini, fallback → OpenRouter **in one run**, asserting which backend served each; quota on the local model does **not** fail over unless `RLA_FALLBACK_ON_QUOTA=1`, and does when set; a terminal fault on one provider does not fan out; an incapable fallback is skipped, not used |
| precedence | session override beats an explicit `model=`; an explicit argument still beats the stage role (**retargeted** test); an empty-string override does **not** win (`is not None`, not truthiness); an override on one role does not leak to another; overrides never reach settings or `.env` |
| `OllamaBackend` | lightweight capability test (embedding model refused, text model accepted); **the real `PaperFacts` schema end-to-end** → valid, non-empty concepts; unknown model → 404 → message naming `ollama pull`; streamed concatenation equals the non-streamed response; every call goes through `call_with_retry` |
| **prefill regression** | the request body carries `format`, and the prompt does **not** grow — a direct guard against reintroducing the ~3.4k-token prefill that made the LiteLLM route 12x slower |
| `doctor` | resolve all roles → canonicalize → deduplicate → exactly one probe per unique model; three roles on one model produce **one** probe; roles listed per model, grouped by provider; embedding probed separately and labelled local/remote |

**Automated gate:** the cross-provider dispatch test passes against the real `PaperFacts` schema —
one Ollama call, valid schema-conformant result, no regression. This is the deterministic gate.

**Manual / integration benchmark:** the ~12x speed-up versus the LiteLLM route. Latency depends on
model load state, machine load and thermal state, so this is recorded as a measured benchmark and
**not** asserted as a CI threshold.

### 9.2 P12b — embedding providers

| area | pinned behaviour |
|---|---|
| batching | `embed_many` issues **one** request for N texts |
| vector identity | cache key differs per canonical embedding model id; a non-canonical spelling shares one entry |
| dimension guard | a mismatch between embedding models still raises `EmbeddingDimensionMismatch` |
| thresholds | `ollama/nomic-embed-text` has no entry ⇒ `auto is None` ⇒ **zero auto-merges**, and judge calls are **≤ `MAX_JUDGE_CALLS`** |
| calibrated model | uses **its own stored calibrated auto threshold**; auto-merges only when `similarity >= that threshold`; does not invoke the judge for those pairs |
| Gemini unchanged | `auto = 0.92`, `maybe = 0.70`, calibrated |
| reporting | the resolve stage emits the UNCALIBRATED warning |
| calibration | never writes a threshold without explicit operator approval |

**Gate:** the full pipeline completes with **zero Gemini calls** when both text and embedding models
are Ollama; switching embedding models never mixes vectors; no threshold is written without
approval.

---

## 10. Milestones

```
P12a — Provider routing            P12b — Embedding providers
    ↓                                   ↓
canonical_model()                      EmbeddingProvider + OllamaEmbedder
MultiBackend                           per-model thresholds + uncalibrated-safe behaviour
OllamaBackend (text)                   calibration pass
precedence contract
CLI + TUI overrides
backend-aware doctor
```

P12a is independently shippable and independently valuable — it is what removes the 12x penalty.
P12b depends on P12a only for provider resolution, which it reuses.

### P12a acceptance

- cross-provider dispatch
- canonical identity, including the ambiguous-bare-id failure before any network call
- session-over-explicit precedence, with the old explicit-wins test retargeted not deleted
- CLI overrides
- Ollama structured generation against the real schema
- capability checks
- fallback behaviour including the quota opt-in
- `doctor --llm` unique-model probes

### P12b acceptance

- batched local embeddings
- model-aware cache identity
- dimension guard
- uncalibrated ⇒ no auto-merge
- judge remains budget-limited
- per-model calibrated thresholds; Gemini `0.92` / `0.70` unchanged
- operator approval required before any threshold is written
- no vector mixing
- a fully local pipeline is possible

---

## 11. Configuration

| Setting | Default | Purpose |
|---|---|---|
| `RLA_OLLAMA_URL` | `http://localhost:11434` | native Ollama endpoint (no `/v1`, no `/api`; the backend appends the path) |
| `RLA_OLLAMA_THINK` | `false` | enable reasoning-model thinking |
| `RLA_STRUCTURED_OUTPUT_MODELS` | `""` | operator declaration of structured-output support — **LiteLLM route only**; unnecessary for native Ollama |
| `RLA_LLM_PROVIDER` | `gemini` | default backend for provider-agnostic calls; whole-run debugging override |
| `RLA_LLM_BASE_URLS` | `""` | per-provider base URL overrides — **LiteLLM route only** |
| `RLA_EMBEDDING_MODEL` | `gemini-embedding-001` | canonical embedding model id; set to `ollama/nomic-embed-text` for the fully local path |

A fully local configuration therefore reads:

```dotenv
GEMINI_API_KEY=...                        # still required; see the note in §7.1
RLA_LLM_PROVIDER=ollama
RLA_STRUCTURED_MODEL=ollama/qwen3:4b
RLA_FAST_MODEL=ollama/qwen3:4b
RLA_ANSWER_MODEL=ollama/qwen3:4b
RLA_EMBEDDING_MODEL=ollama/nomic-embed-text
RLA_FALLBACK_MODELS=gemini/gemini-2.5-flash
RLA_OLLAMA_URL=http://localhost:11434
RLA_LLM_DAILY_BUDGET=0
```

and the mixed configuration this was designed for:

```dotenv
RLA_STRUCTURED_MODEL=ollama/qwen3:4b        # bulk: unlimited
RLA_ANSWER_MODEL=gemini/gemini-2.5-flash    # 1 call per question, quality matters
RLA_EMBEDDING_MODEL=gemini/gemini-embedding-001
RLA_FALLBACK_MODELS=gemini/gemini-2.5-flash,openrouter/ling-3.0-flash-sante:free
```

`EMBEDDING_THRESHOLDS` is code, not configuration: thresholds are a correctness decision reviewed and
committed, not a dial turned at runtime.

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A local model produces valid but shallow extractions | Medium | measured on this machine: 1–4 concepts per paper versus Gemini's ~5–6. Accepted as a quality trade for unlimited throughput; the extraction report makes the count visible |
| Over-merge when embedding models change | High | auto-merge is **off** for any uncalibrated model; judge bounded by `MAX_JUDGE_CALLS`; thresholds keyed by canonical model id |
| Ollama slower than expected | Low | local ~8s vs the cloud's ~18s per extraction call at best; a local server that is down falls back per the existing chain |
| Lazy backend construction reintroduces a hard import | Low | the A1 structural test must be extended to cover `ollama_backend.py` as an allowed adapter module |
| The precedence change weakens explicit-model behaviour unintentionally | Medium | the retargeted test asserts explicit still beats the stage role; a separate test asserts only the session rung sits above it |

---

## 13. Documentation deliverables

- `docs/OPERATIONS_GUIDE.md` §3.3 precedence contract, §3.4 model resolution table, §5 local setup.
- `PLAN.md` gains a P12 row with the achieved/not-achieved verdict format used by every other
  milestone.
- `.env.example` documents `RLA_OLLAMA_URL` and `RLA_OLLAMA_THINK`, and notes that
  `RLA_STRUCTURED_OUTPUT_MODELS` is LiteLLM-only.
- ADR `0006-multi-provider-dispatch.md` — why `MultiBackend` rather than a router rewrite.
- ADR `0007-per-embedding-model-merge-thresholds.md` — why an uncalibrated space disables
  auto-merge rather than inheriting another's numbers.

## 14. Open questions

None. The following were resolved during design and are recorded above: switching granularity
(both), bare-id ambiguity policy (error), precedence change (accepted, contract updated), TUI
exposure (panel plus CLI flags, transient), embeddings in scope (yes), threshold handling
(per-model, uncalibrated-safe), latency gate (benchmark, not CI).