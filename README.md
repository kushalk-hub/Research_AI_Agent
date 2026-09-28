# rla — Graph-Based Research Literature Agent

Ingests papers on a research topic, builds a citation-and-concept graph, and traverses
that graph to answer lineage questions ("how did technique X evolve?") and gap questions
("what's still unsolved in Y?") with traceable citations.

---

## Setup

**Requires Python 3.11+.** This project was built and verified on 3.12.

```powershell
# 1. create the environment
py -3.12 -m venv .venv

# 2. install (this creates the `rla` command)
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"

# 3. add your API key — see "API keys" below
Copy-Item .env.example .env
```

Activate it if you prefer: `.\.venv\Scripts\Activate.ps1`
Otherwise prefix commands with `.\.venv\Scripts\`.

> **Note:** `python -m src.rla.cli` does **not** work. This is a src-layout package and
> the import name is `rla`. Use the `rla` command, or
> `$env:PYTHONPATH="src"; python -m rla.cli` if you have not installed.

### Verify

```powershell
rla doctor          # config, sources, cache — no API key needed
rla doctor --llm    # live check of every configured model (spends a few requests)
```

---

## API keys

**One key, in `.env`.** Add it under `GEMINI_API_KEY`:

```dotenv
GEMINI_API_KEY=your-key-here
```

Get one from [Google AI Studio](https://aistudio.google.com/apikey).

- **Without a key** the pipeline still works. It acquires a corpus from the keyless
  sources (Semantic Scholar, OpenAlex, arXiv, DBLP, CrossRef) and skips the LLM stages.
  `rla build` and `rla report` are useful with no key at all.
- **With a key** you additionally get query expansion, relevance scoring, concept
  extraction, entity resolution, and answer generation.
- `.env` is gitignored. `.env.example` is the committed template — never put a real key
  in it.
- Use an **AI Studio API key**, not `gcloud auth print-access-token` output. An OAuth
  token returns `401` on every call and `rla doctor --llm` will say so.

Other optional keys, all documented in `.env.example`: `RLA_SERPAPI_API_KEY` (adds a
Google Scholar pass for recent preprints), `RLA_UNPAYWALL_EMAIL`, `RLA_NEO4J_*`.

---

## Choosing a provider (LiteLLM routing)

The application talks to one interface, `LLMClient`. Underneath, you can use the **native
Google SDK** or route through **LiteLLM**. One env var switches between them — no code
change.

```dotenv
# native Google SDK (default, no extra install)
RLA_LLM_PROVIDER=gemini

# route through LiteLLM
RLA_LLM_PROVIDER=litellm
```

### Enabling LiteLLM

LiteLLM is an **optional extra**, so the default install stays small:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[router]"
```

It still uses the **same `GEMINI_API_KEY`**. LiteLLM does not need a separate key — it
reads the standard variable for whichever provider you route to. For a second provider
(e.g. OpenAI) you would add that provider's own key to `.env`.

### Which model runs each stage

| Setting | Used for | Default |
|---|---|---|
| `RLA_FAST_MODEL` | generic fallback | `gemini-2.5-flash-lite` |
| `RLA_STRUCTURED_MODEL` | the 4 schema-constrained stages | falls back to `fast_model` |
| `RLA_ANSWER_MODEL` | streamed answer generation | falls back to `strong_model` |
| `RLA_EMBEDDING_MODEL` | concept embeddings | `gemini-embedding-001` |
| `RLA_FALLBACK_MODELS` | comma-separated fallbacks, in order | `gemini-2.5-flash` |

**The free tier allows ~20 requests per model per day.** A 100-paper corpus needs ~100
extraction calls, so keep `RLA_STRUCTURED_MODEL` on the cheap model unless you have a paid
key. The fallback chain exists because quota is **per model** — when the fast model's
allowance is spent, the fallback model may still have budget.

### Fallback behaviour

Fallback triggers only on recoverable faults: timeout, per-minute 429, 5xx, network error.
It does **not** trigger on invalid credentials, malformed config, unsupported schema, or
programming errors — retrying those across models just multiplies the cost of a one-line
fix.

Daily-quota exhaustion is treated as a capacity condition, not a fault, so it raises
rather than failing over (preserving the other model's budget). Opt in with:

```dotenv
RLA_FALLBACK_ON_QUOTA=true
```

A model is only used for a structured stage if it supports schema-constrained output;
otherwise the router refuses it rather than silently degrading to unvalidated JSON.

### Per-provider base URLs

Point any provider at an alternative endpoint — an OpenAI-compatible gateway, a proxy, or
a self-hosted server — without touching code:

```dotenv
RLA_LLM_BASE_URLS={"openai": "http://localhost:8000/v1", "openrouter": "https://openrouter.ai/api/v1"}
```

Keyed by the **same provider prefix** used in model strings, so
`openrouter/meta/llama-3` picks up the `openrouter` entry.

**The prefix must be a provider LiteLLM actually recognises** — `openai`, `openrouter`,
`groq`, `gemini`, `anthropic`. An invented name like `local` is rejected with
`LLM Provider NOT provided` before any request goes out. To reach a custom
OpenAI-compatible server, declare it *as* `openai` and override the endpoint:

```dotenv
RLA_LLM_BASE_URLS={"openai": "http://localhost:8000/v1"}
RLA_FALLBACK_MODELS=openai/my-model
```

The credential sent is the one that provider reads, so the entry above sends
`OPENAI_API_KEY` to your server.

It is a **map, not a single URL**, deliberately. During cross-provider failover two
providers are live at once, and a shared endpoint would silently break the primary.

Entries are optional: an absent key means "use the provider's default endpoint", which is
what you want for `openrouter` and `groq` since LiteLLM already knows those URLs. A bare
model id (`gemini-2.5-flash`) is treated as the primary provider, so a `gemini` key applies
to the project's default model strings. Malformed JSON is ignored with a warning rather than
stopping the pipeline.

Applies to the **LiteLLM path only** — the native Gemini backend talks directly to Google.

### Adding a second provider

```dotenv
GEMINI_API_KEY=...          # primary
OPENAI_API_KEY=...          # second provider, independent credential
RLA_FALLBACK_MODELS=openai/gpt-4o-mini
```

The key is named for the **provider**, not the routing role. A `FALLBACK_API_KEY` would
become wrong the moment that provider is promoted to primary. Provider selection stays in
configuration; no pipeline stage knows which provider is serving it.

The router will only use the second provider for a stage if it reports support for that
stage's capabilities — see the matrix below.

### Provider capability differences are real

LiteLLM is not a universal equaliser. Structured-output support is genuinely
provider-dependent, which is why the capability gate exists. Current status:

| Provider | Structured output | Status |
|---|---|---|
| Gemini (native or via LiteLLM) | server-side constrained decoding | **verified live** |
| OpenAI (via LiteLLM) | `json_schema` strict mode | not yet exercised |
| Anthropic (via LiteLLM) | no native constraint; weaker | not yet exercised |

Only Gemini has been validated. See
[`docs/llm_provider_validation.md`](docs/llm_provider_validation.md).

---

## Commands

| Command | What it does | Needs a key? |
|---|---|---|
| `rla doctor [--llm]` | config, sources, cache. `--llm` probes every model live | `--llm` only |
| `rla sources` | probe each source API to see which actually respond | no |
| `rla stats` | summarise the stored corpus and graph | no |
| `rla events` | print the pipeline phase order | no |
| `rla build -t "topic"` | fetch 40-100 papers from all sources | no |
| `rla run -t "topic" -q "question"` | full pipeline, streaming events as they happen | optional |
| `rla ask "question"` | answer from the built graph (no re-acquisition) | for the answer |
| `rla report` | per-paper limitations + synthesized cross-paper gaps | no |
| `rla eval` | evaluation report → `data/eval/report.md` | no |
| `rla tui -t "topic"` | live terminal UI (needs `textual`; use Windows Terminal) | optional |

Add `--jsonl` to `run`, `ask`, or `report` for machine-readable output.

### Typical first run

```powershell
rla sources                 # confirm the source APIs work
rla build -t "Graph-based agent architectures"
rla run -t "Graph-based agent architectures" -q "How did GAT evolve?"
```

`rla ask` and `rla eval` need `data/graph/graph.json`, which only exists after a run that
built a graph. That path is gitignored, so a fresh clone has no graph.

---

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q      # 507 tests, ~70s
.\.venv\Scripts\python.exe -m ruff check src/ tests/  # lint
```

Run a single module or test:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p9_provider_routing.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -k fallback
```

**Use the venv's tools, not the ones on `PATH`.** The system Python may lack `respx`
(breaking test collection) and ships an older `ruff` that reports failures the pinned
version does not.

Test files are named `test_p<N>_*.py` after the `PLAN.md` milestone they gate, not after
the module under test.

---

## Architecture

```text
Pipeline stages  →  LLMClient Protocol  →  ProviderRouter  →  ┬→ GeminiClient (native SDK)
                                                          └→ LiteLLMBackend (optional)
```

Pipeline stages never import a provider SDK. `ProviderRouter` owns model selection,
capability gating, and fallback; retry, rate limiting, budget, and SQLite caching stay in
`rla.llm.retry` / `rla.store.cache` so there is exactly one retry layer.

Sources, stores, and the evaluation harness are unchanged by the routing work.

## Documentation

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Conventions and gotchas for coding agents |
| [`docs/llm_architecture_audit.md`](docs/llm_architecture_audit.md) | Audit of the LLM layer before the migration |
| [`docs/llm_provider_migration_plan.md`](docs/llm_provider_migration_plan.md) | Migration design, ADRs, rollback |
| [`docs/llm_provider_validation.md`](docs/llm_provider_validation.md) | Real-provider validation results |
| [`PLAN.md`](PLAN.md) | Milestones P0-P9 and their acceptance gates |

## Known limitations

- **The Gemini free tier cannot complete a full run.** ~20 requests/model/day against
  ~100 extraction calls for a 100-paper corpus. A paid key is needed for the full
  pipeline; the free tier works for single commands and development.
- **`rla eval` reports `NOT MEASURED` for extraction accuracy** because the shipped
  reference set is not hand-labelled. The harness refuses to invent the number.
- **Only Gemini has been validated through the routing layer.** No second provider is
  configured.
- **Textual needs Windows Terminal**, not legacy conhost.

## License

See repository history. `research-literature-agent-project-final.md` is the read-only
original specification.
