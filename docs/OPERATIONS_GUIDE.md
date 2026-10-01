# Operations guide — how `rla` actually works

Everything you need to run the system, drive it from any surface, understand how a model gets
chosen for a stage, and change any limit it obeys.

Companion documents:

| Document | Covers |
|---|---|
| [`../PLAN.md`](../PLAN.md) | what is built, and whether each target was achieved |
| [`research-literature-agent-project-final.md`](../research-literature-agent-project-final.md) | the original read-only specification (§N references point here) |
| [`demo_commands.md`](demo_commands.md) | command-by-command manual checks with expected output |
| [`env_loading.md`](env_loading.md) | how `.env` is found and resolved |
| [`llm_provider_migration_plan.md`](llm_provider_migration_plan.md) | why the routing layer exists |
| [`adr/`](adr/) | the five decisions behind the LLM layer |

Verified against the working tree on 2026-10-01.

---

## 1. What the system is

One topic string goes in. Ten phases run. A graph and a set of files come out, and every sentence
the system later says traces back to a stored extraction or a citation edge.

```text
title ─▶ SEARCH ─▶ FETCH ─▶ SCORE ─▶ FULLTEXT ─▶ EXTRACT ─▶ RESOLVE ─▶ GRAPH ─▶ TRAVERSE ─▶ ANSWER ─▶ DONE
         │         │        │         │(stub)     │          │          │         │        │
     queries   5 sources  1-5      no code   concepts  merged   graph.json  subgraph  narrative
               +snowball  relevance          per paper concepts  +graphml   [P1][C5]  +citations
```

Phase order is fixed in `src/rla/events.py:PIPELINE_PHASES`. It is not decoration: the TUI status
bar renders one slot per phase, and the 80×24 frame tests assert all ten are on screen and uncut.
Phases are walked **in order**, and an unimplemented or unreachable phase emits a `pending` event
rather than being skipped silently — which is why `FULLTEXT` appears as a visible slot even though
Phase 2 does not exist.

### What each phase writes to disk

| Phase | File | Written by |
|---|---|---|
| FETCH / SCORE | `data/corpus.json` | orchestrator, after acquisition |
| EXTRACT | `data/extractions.jsonl` | `store/extraction_store.py`, one JSON object per paper |
| RESOLVE | `data/concepts.json` | orchestrator: `{concepts: [...], decisions: [...]}` |
| GRAPH | `data/graph/graph.json`, `data/graph/graph.graphml` | `store/graph_store.py` |
| every outbound call | `data/cache.db` | `store/cache.py` (HTTP **and** LLM) |
| EVAL | `data/eval/report.md`, `data/eval/results.json` | `eval/run_eval.py` |
| source responses | `data/raw/` | debug only, gitignored |

`data/graph/` is gitignored, so a fresh clone has no graph and `rla ask` / `rla eval` will refuse
to run until something has built one. `data/corpus.json`, `data/extractions.jsonl` and
`data/concepts.json` **are** committed, deliberately, so evaluation numbers reproduce.

### The two non-negotiable invariants

1. **One event stream.** `Pipeline.run()` is an `async for` generator of
   `Event(phase, kind, message, payload)`. Stages never yield; they take an `Emitter` callback.
   `rla run` and `rla tui` both iterate that one generator, so the UI and the headless log cannot
   drift apart. `cli._build_pipeline()` exists for exactly this reason — `run` and `tui` build the
   pipeline through the same function.
2. **Everything outbound goes through the SQLite cache.** HTTP and LLM alike. Cache keys include
   `prompt_hash(prompt)` and the model id, so editing a prompt invalidates exactly the calls that
   used it and nothing else. A second identical run costs zero network calls — including streamed
   answers, which replay from cache as a single chunk.

---

## 2. Every way to reach the pipeline

There are five surfaces. They share the same pipeline; they differ only in what they do with the
event stream.

### 2.1 CLI

Ten commands. `rla --help` lists them; `rla events` prints the phase order.

```powershell
rla doctor [--llm]                        # config, sources, cache; --llm probes models live
rla sources [--probe "query"] [--cache]    # is each source actually answering right now?
rla stats                                  # corpus + graph summary tables
rla events                                 # the 10 phases, in order
rla build  -t "Topic" [--jsonl]            # acquisition only
rla run    -t "Topic" [-q "Q"] [--jsonl]  # full pipeline, streaming events
rla ask     "Q" [--markdown] [--jsonl]    # answer from the built graph
rla report  [--markdown/--no-markdown] [--jsonl]   # limitations + synthesized gaps
rla eval                                   # evaluation report
rla tui    -t "Topic" [-q "Q"]             # live terminal UI
```

Notes that save time:

- `--jsonl` exists on `run`, `build`, `ask` and `report`. On `run`/`build` it emits **one JSON
  object per event, as it happens**. On `report` it emits the whole report as one JSON document.
- `build` and `run` prompt for a title if you omit `-t`, so both work interactively.
- `ask` takes the question as a **positional argument**, not `-q`.
- `report` costs nothing — every claim comes from a stored extraction or a graph edge.
- `doctor --llm` is deliberately **uncached**: a cache-first probe would report a stale green from a
  call that succeeded under an earlier key, which is precisely what that command exists to detect.

### 2.2 JSONL (scripting and piping)

```powershell
# live stream, one event per line, suitable for a log file or jq
rla run -t "Graph Attention Networks" -q "How did GAT evolve?" --jsonl |
  jq -r 'select(.kind=="ok") | "\(.phase)\t\(.message)"'

# count events per phase, no jq needed
rla build -t "Graph Attention Networks" --jsonl |
  ForEach-Object { ($_ | ConvertFrom-Json).phase } | Group-Object

# or, with jq: phases only, first ten lines
rla build -t "Graph Attention Networks" --jsonl | jq -r '.phase' | head -10

# machine-readable gap report
rla report --jsonl | jq '.ranked'
```

Each line has exactly `{"phase", "kind", "message", "payload", "timestamp"}`. `kind` is one of
`info`, `ok`, `warn`, `error`, `pending`, `delta`. **`delta` events are answer text fragments** —
they are the streaming answer, so filtering them out of a log keeps the narrative intact.

### 2.3 TUI

```powershell
rla tui -t "Graph Attention Networks" -q "How did GAT evolve?"
```

Requirements: the `tui` extra (`pip install -e ".[tui]"`) and **Windows Terminal**. Legacy conhost
renders it wrong — this is documented, not a bug.

What is on screen:

| Panel | Source | Behaviour |
|---|---|---|
| status strip | `PipelineState.status_line` | current phase + elapsed clock, width-aware, re-rendered on resize |
| counters | `PipelineState.counter_line` | running paper / concept / edge counts while the graph builds |
| event log | `RichLog` | colour-coded by `kind`, **wraps** rather than truncating, `delta` and `done` suppressed because the text lives in the answer panel |
| tree | `rich.tree.Tree` | the traversal, built from the reducer's `TreeNode` |
| answer | streamed | grows as `delta` events land, with the cited labels appended |

Keys: `q` quit, `c` clear log.

The pipeline runs in a Textual worker on the event loop. Each event is a cheap `update()` on
already-mounted widgets, so a slow network stage cannot freeze the render loop; a crash inside a
stage is caught and rendered as an `error` event rather than taking the UI down.

### 2.4 CLI vs TUI — same or different?

**Same engine, different presentation.** They cannot behave differently in substance, and here is
exactly why:

| | `rla run` | `rla tui` |
|---|---|---|
| pipeline instance | `_build_pipeline()` | `_build_pipeline()` — the same function |
| event stream | `async for evt in pipeline.run(...)` | `async for evt in pipeline.run(...)` |
| cache lifetime | closed in `_stream`'s `finally` | closed in the generator's `finally` |
| what it adds | a coloured one-line-per-event print | status strip, counters, tree, streamed answer panel |

The genuine differences, all presentational or ergonomic:

- **The TUI shows a phase strip and live graph counters.** The CLI has neither; you infer progress
  from the event lines.
- **The TUI collapses answer `delta` events into the answer panel.** The CLI prints them inline,
  interleaved with the event log, so a long answer makes the log harder to scan.
- **The TUI renders only when an event arrives, plus a 0.5 s tick** for the elapsed clock
  (`TICK_SECONDS`). The CLI prints as it goes, so it reflects sub-event progress the TUI does not.
- **The TUI prints a missing-key warning *before* taking over the screen**, otherwise it scrolls
  off unseen. The CLI prints it inline.
- **Neither can re-acquire on `ask`-style questions.** Only `run` and `tui` drive acquisition.
- **The TUI is not scriptable.** There is no `--jsonl` equivalent; if you want machine output, use
  `run`.

Practical rule: **debug with `rla run`, demo with `rla tui`.** Because they share the stream, a bug
you cannot see in the TUI is a rendering question, not a pipeline question.

### 2.5 Python API

The pipeline is a library, not just a CLI. All examples run from the repo root.

**Drive the whole pipeline and collect events:**

```python
import asyncio
from rla.config import get_settings
from rla.llm.factory import build_client
from rla.store.cache import Cache, CostTracker
from rla.pipeline.orchestrator import Pipeline, PipelineResult

async def main() -> None:
    settings = get_settings()
    cache = Cache(settings.cache_db)
    tracker = CostTracker()
    result = PipelineResult()
    pipeline = Pipeline(settings, build_client(settings, cache, tracker), cache, tracker)
    async for evt in pipeline.run("Graph Attention Networks", "How did GAT evolve?", result):
        print(evt.phase, evt.kind, evt.message)
    print(result.corpus.stats(), result.stats["llm"])
    cache.close()

asyncio.run(main())
```

`build_client(...)` returns **`None` when `GEMINI_API_KEY` is blank**, and the pipeline treats that
as degrade mode rather than an error — the same behaviour `rla build` relies on.

**Traverse without any model call at all** (traversal is pure code):

```python
from rla.config import get_settings
from rla.store.graph_store import load
from rla.pipeline.traverse import QuestionType, classify_question, traverse

g = load(get_settings().graph_json)
q = "how did graph attention networks evolve?"
print(classify_question(q))                       # QuestionType.LINEAGE
sub = traverse(g, q, QuestionType.LINEAGE)       # classification is optional; it defaults
print(sub.to_payload()["stats"])                  # {'nodes': N, 'edges': M, ...}
print(sub.render())                               # the exact text the answer LLM would see
```

**Answer with a stream you control:**

```python
from rla.config import get_settings
from rla.llm.factory import build_client
from rla.store.cache import Cache, CostTracker
from rla.store.graph_store import load
from rla.pipeline.answer import answer_question

settings = get_settings()
client = build_client(settings, Cache(settings.cache_db), CostTracker())
async for evt in answer_question(load(settings.graph_json), "how did GAT evolved?", client):
    if evt.kind == "delta":
        print(evt.message, end="", flush=True)
```

**Gap analysis is pure too** — no I/O, no model:

```python
from rla.config import get_settings
from rla.models import Corpus
from rla.store.extraction_store import ExtractionStore
from rla.store.graph_store import load
from rla.pipeline.gaps import build_gap_report, render_report

s = get_settings()
store = ExtractionStore(s.extractions_path); store.load()
corpus = Corpus.model_validate_json(s.corpus_path.read_text("utf-8"))
report = build_gap_report(store.all(), load(s.graph_json), corpus.papers)
print(render_report(report))
```

### 2.6 The evaluation harness as an entry point

`rla eval` is a fifth surface rather than a pipeline phase: it reads the corpus, the extraction
store and the graph, and compares two retrieval arms. It costs no LLM requests in its retrieval
arms. `eval/run_eval.py` is importable — `run_eval(settings)` returns a report object with
`to_dict()`, and `render_table(report)` produces the Markdown.

---

## 3. Model routing

The routing layer exists because "add a provider" originally was not actually true: the Protocol
claimed one class plus a key would do it, while three call sites named `GeminiClient` directly. An
audit found that and three other latent defects; P9 fixed all four.

### 3.1 The stack

```text
pipeline stage  →  LLMClient (Protocol)  →  ProviderRouter  →  ┬→ GeminiClient   (native google-genai)
                                                             └→ LiteLLMBackend (optional, `[router]`)
```

Pipeline stages **never** import a provider SDK. That is enforced by a structural test
(`test_a1_no_pipeline_module_imports_a_provider_sdk`) that walks the AST of every module outside
`llm/` — AST, not text matching, because the docstrings legitimately mention `google.genai` and
`litellm` and a text-based guard would flag its own documentation and then get deleted.

`ProviderRouter` has exactly three responsibilities, and deliberately not more:

1. **Model selection per stage** — no stage hard-codes a model id.
2. **Capability gating** — a model that cannot do what the stage needs is *refused*, not used in a
   degraded mode. This is what stops the abstraction collapsing to a lowest common denominator.
3. **Fallback** across the configured chain, on recoverable faults only.

It deliberately does **not** own retry, pacing, budget or caching. Those stay in `llm/retry.py` and
`store/cache.py`, so there is exactly one retry layer and a call can never retry twice (ADR-003).

### 3.2 Choosing the provider

One env var. No code change.

```dotenv
RLA_LLM_PROVIDER=gemini     # default: native Google SDK, 7 runtime deps
RLA_LLM_PROVIDER=litellm    # route through LiteLLM (pip install -e ".[router]")
```

An unrecognised value is a **configuration error, not a silent default**:

```text
ValueError: unknown RLA_LLM_PROVIDER 'nonsense'; expected one of gemini, litellm
```

LiteLLM is imported *inside a function* in `litellm_backend.py`, so the default install never loads
it and the extra can be removed without breaking the direct path. There is a test that asserts no
module-scope `import litellm`.

### 3.3 Choosing the model — the precedence rules

For every call, `ProviderRouter.model_for(stage, explicit)` resolves in this order:

1. **An explicit `model=` argument wins.** Always. No exceptions.
2. **The stage's configured role** wins next:
   - `answer` → `RLA_ANSWER_MODEL`, falling back to `RLA_STRONG_MODEL`
   - `query_expansion`, `relevance_scoring`, `extraction`, `resolution` → `RLA_STRUCTURED_MODEL`,
     falling back to `RLA_FAST_MODEL`
   - any other stage (e.g. `doctor`) → `RLA_FAST_MODEL`
3. Nothing else. There is no heuristic, no load balancing, no cost optimisation.

| Setting | Used for | Default | `.env` here |
|---|---|---|---|
| `RLA_FAST_MODEL` | generic fallback, `doctor` probes | `gemini-2.5-flash-lite` | as default |
| `RLA_STRONG_MODEL` | fallback for `RLA_ANSWER_MODEL` | `gemini-2.5-flash` | as default |
| `RLA_STRUCTURED_MODEL` | the schema-constrained stages | *empty* → `fast_model` | unset |
| `RLA_ANSWER_MODEL` | streamed answer generation | *empty* → `strong_model` | unset |
| `RLA_EMBEDDING_MODEL` | concept embeddings | `gemini-embedding-001` | as default |
| `RLA_FALLBACK_MODELS` | ordered fallback chain, comma-separated | `gemini-2.5-flash` | `ling-3.0-flash-sante:free` |

**An empty role setting means "inherit", not "use nothing".** That is why `structured_model`
defaults to `""` and not to `strong_model`: the structured stages are the bulk of the request
volume (a 100-paper corpus is ~100 extraction calls, which is five days of the free tier's daily
allowance), so defaulting them to the *expensive* model would be wrong on a free key.

### 3.4 An explicit model beats the configured role

Rule 1 has a sharp edge, and it caused a real defect. `pipeline/orchestrator.py` used to pass
`model=self.settings.strong_model` explicitly into `extract_papers(...)` and `resolve_concepts(...)`.
Because an explicit argument wins, extraction and resolution ran on `RLA_STRONG_MODEL` and
**silently ignored `RLA_STRUCTURED_MODEL`** — for the two stages that spend the most requests.
Reproduced with distinct settings:

```text
A) router resolves by stage:
  stage=query_expansion      model=STRUCTURED
  stage=relevance_scoring    model=STRUCTURED
  stage=extraction           model=STRUCTURED
  stage=resolution           model=STRUCTURED
B) what the orchestrator actually passed (the real pipeline path), before the fix:
  stage=extraction           model=STRONG
  stage=resolution           model=STRONG
```

**Fixed.** The orchestrator now passes `settings.model_for_structured`, so `RLA_STRUCTURED_MODEL`
reaches all four structured stages and you can move extraction onto a model that still has quota by
configuration alone. Pinned by `test_p0_orchestrator.py`.

The rule itself is unchanged and is worth remembering when adding a caller: **pass no model id and let
the router resolve it**, or the setting you are trying to change will be ignored without warning.

### 3.5 The capability gate

LiteLLM is not a universal equaliser: structured-output support is genuinely provider-dependent.
So the router **asks** the backend (`supports(model, "supports_structured_output")`) and refuses an
unqualified model for a structured stage:

```text
model 'anthropic/claude-…' does not support schema-constrained output, which this stage
requires; refusing rather than degrading to unvalidated JSON
```

Two consequences:

- A backend that **cannot answer** the capability question is treated as *not* supporting it.
  Assuming capability for an unknown provider is exactly how structured output degrades silently.
- An incapable **fallback** is skipped, not used. If every candidate is incapable the stage raises
  `ProviderUnsupported` without making a single request.

Current provider status (`llm_provider_validation.md`): Gemini **verified live**; OpenAI and
Anthropic are configured paths that have not been exercised. The capability matrix is real, and
treating it as cosmetic is what the gate exists to prevent.

**The self-hosted exception.** LiteLLM has no static entry for a local server, so it answers `False`
for every model served by one — and that answer is not even stable, since it changes with what
earlier code in the process already touched. `RLA_STRUCTURED_OUTPUT_MODELS` is therefore an
explicit operator assertion that overrides it. Empty preserves the refusal, which is the whole point
of ADR-004: the degradation must never be *silent*. See §5 for the full local-inference setup.

### 3.6 Fallback

```dotenv
RLA_FALLBACK_MODELS=gemini-2.5-flash,openai/gpt-4o-mini
RLA_FALLBACK_ON_QUOTA=false
```

Chain construction: `[primary, *fallbacks excluding the primary]`, order preserved, de-duplicated.
Only the model being asked about is excluded — excluding the answer-stage primary too would leave
the structured stages (the bulk of the volume) with nothing to fail over to, since the two primaries
are sibling models and the structured primary is the cheaper one.

**What triggers a fallback:**

| Error category | Retried? | Fallback? | Why |
|---|---|---|---|
| `timeout` | yes | **yes** | transient; a different model may answer faster |
| `rate_limited` (per-minute 429) | yes | **yes** | transient burst |
| `server_error` (5xx) | yes | **yes** | transient |
| `network_error` | yes | **yes** | transient |
| `quota_exhausted` | **no** | **only if `RLA_FALLBACK_ON_QUOTA=1`** | a capacity condition, not a fault |
| `auth_failed` | no | no | a different model will not fix a bad key |
| `invalid_request` (400/404) | no | no | fanning out multiplies the cost of a one-line fix |
| `unsupported` | no | no | structural, not per-model |
| `structured_output` | no | no | the schema is the problem, not the model |
| `budget_exhausted` | no | no | local, not the provider |

Retry-ability and fallback-ability are **derived from the category**, never re-decided per call
site. That is what stops the retry layer from silently disabling failover (a failure mode the audit
found: wrapping the final error in a bare `LLMError` discarded the status code, downgraded a 503 to
`UNKNOWN`, and the router then refused to fall back).

**Quota is excluded by default, deliberately.** Falling over on the first model's ceiling spends
the reserve you wanted kept, invisibly, one level above where `RLA_LLM_DAILY_BUDGET` protects you.
Opt in explicitly, and the error message then tells you what is available:

```text
daily free-tier quota exhausted (…perday…). A different model may still have budget
(gemini-2.5-flash); set RLA_FALLBACK_ON_QUOTA=1 to fail over automatically, or switch the
stage's model via RLA_STRUCTURED_MODEL / RLA_ANSWER_MODEL.
```

**Streaming never falls back mid-stream.** Once bytes have reached the user, silently switching
models would splice two different answers together. If the primary fails before the first chunk the
error propagates and the stage's own degradation handles it.

### 3.7 Cache, pacing, budget

- **Cache first, always.** Every LLM call is keyed on model + prompt hash + schema. A hit makes
  zero provider calls and is never charged. Streaming replays from cache as one chunk.
- **Pacing.** `RLA_LLM_RPM` (default 15) is a shared limiter across text *and* embedding calls, one
  per process, keyed to the running event loop. It is **not the binding constraint**: the free tier
  also caps each model at a fixed number of requests *per day*, and that ceiling resets only at the
  daily boundary, so no amount of pacing gets under it.
- **Daily quota is detected, not guessed.** `llm/error_map.py:_looks_like_period_quota` looks at the
  `quotaId` in the 429 body — Gemini names
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier` — because a real captured per-day 429 carries
  both the quota id *and* a "retry in Ns" hint, and trusting the hint turns every daily-cap failure
  into three pointless retries before the same terminal error.
- **Per-run budget.** `RLA_LLM_DAILY_BUDGET` (default 15, here 200) is a **local** cap on requests
  per model per run. It exists so a large batch cannot spend the whole day's allowance on its first
  pass and leave nothing for resolution, graph building or answering. Set `0` for no cap. The
  spender is reset at the start of every `Pipeline.run()`, because it is a process-global singleton
  keyed to the event loop.
- **Timeout.** `RLA_LLM_TIMEOUT_SECONDS` (default 120) bounds a single provider attempt. It is
  separate from `RLA_REQUEST_TIMEOUT_SECONDS`, which only ever applied to academic source HTTP.
  A timeout is retryable and normalises to the `timeout` category, so the router may fall back from
  it.
- **Cost accounting.** Token counts accumulate per stage; unknown usage is reported as *unknown*,
  never as `$0.00`. A cache hit records unknown usage, because a cached call genuinely has no
  provider response to meter — recording zero would make a fully cached run report a total that is
  right by accident and wrong for a partial hit.

---

## 4. Every limit and rule, and how to change it

Two kinds of knob: **configuration** (env var → `.env`, no code change) and **constants**
(module-level, changed in source and covered by tests).

### 4.1 Configuration

| Env var | Default | Bounds | What it does | Change it when |
|---|---|---|---|---|
| `GEMINI_API_KEY` | `""` | — | The only credential the MVP needs. Blank ⇒ degrade mode | Always; `rla doctor --llm` verifies it |
| `OPENAI_API_KEY` | `""` | — | Credential for a **second provider**. Named for the provider, not the routing role: a provider can be promoted to primary later, at which point `FALLBACK_API_KEY` would be actively misleading | You want cross-provider failover |
| `RLA_LLM_PROVIDER` | `gemini` | `gemini` \| `litellm` | Which backend serves every call | Switching providers |
| `RLA_FAST_MODEL` | `gemini-2.5-flash-lite` | — | Generic fallback; also what `doctor` probes | A tier change |
| `RLA_STRONG_MODEL` | `gemini-2.5-flash` | — | Fallback for the answer model. **Also what extraction and resolution actually use** (§3.4) | Cost control on a free key |
| `RLA_STRUCTURED_MODEL` | `""` → `fast_model` | — | Model for the schema-constrained stages. See §3.4 for what really honours it | Balancing cost vs extraction quality |
| `RLA_ANSWER_MODEL` | `""` → `strong_model` | — | Streamed answer generation, where quality is user-visible and volume is one call per question | Answer quality matters more than cents |
| `RLA_EMBEDDING_MODEL` | `gemini-embedding-001` | — | Concept embeddings. Cache keys are model-aware, so changing it invalidates stored vectors | `text-embedding-004` is retired and 404s; this is the GA replacement |
| `RLA_FALLBACK_MODELS` | `gemini-2.5-flash` | comma list | Ordered fallback chain | You have a second provider |
| `RLA_FALLBACK_ON_QUOTA` | `false` | bool | Allow failover on quota exhaustion | You would rather spend the reserve than fail |
| `RLA_STRUCTURED_OUTPUT_MODELS` | `""` | comma list | Assert that these models honour schema-constrained output, overriding LiteLLM's static table. Needed for any self-hosted server | Routing a structured stage to a local model |
| `RLA_LLM_TIMEOUT_SECONDS` | `120` | `> 0` | Bound on one provider attempt | A slow provider hangs a stage |
| `RLA_LLM_BASE_URLS` | `""` | JSON object | Per-provider base URL overrides | A gateway, proxy or self-hosted server |
| `RLA_LLM_RPM` | `15` | `1..60` | Shared per-minute pacing, text + embeddings | Burst control; **not** the quota fix |
| `RLA_LLM_MAX_RETRIES` | `5` | `1..10` | Attempts per logical call | A flaky provider |
| `RLA_LLM_DAILY_BUDGET` | `15` | `>= 0` (`0` = uncapped) | Local per-run request allowance per model | You want the first stage to stop before the day's allowance is gone |
| `RLA_MAX_CONCURRENCY` | `4` | `1..16` | Fan-out width for sources, extraction, judging | More throughput / gentler on APIs |
| `RLA_S2_DELAY_SECONDS` | `1.1` | `>= 0` | Min seconds between Semantic Scholar calls; its anonymous pool is shared | S2 throttles you |
| `RLA_TARGET_CORPUS_MIN` | `40` | — | Lower bound on the working corpus | This machine uses `15` |
| `RLA_TARGET_CORPUS_MAX` | `100` | — | Upper bound; also the trim cap | This machine uses `30` |
| `RLA_REQUEST_TIMEOUT_SECONDS` | `30.0` | — | Timeout for **source** HTTP only | A slow index |
| `RLA_MAX_RETRIES` | `4` | — | Retries for source HTTP | A flaky index |
| `RLA_SERPAPI_API_KEY` | `""` | — | Enables the Google Scholar pass | Recent preprints are a blind spot |
| `RLA_CORE_API_KEY` | `""` | — | Reserved. No adapter exists | Phase 2 |
| `RLA_UNPAYWALL_EMAIL` | `""` | — | Reserved. No adapter exists | Phase 2 |
| `RLA_GROBID_URL` | `""` | — | Reserved. No adapter exists | Phase 2 |
| `RLA_NEO4J_URI` / `_USER` / `_PASSWORD` | localhost / `neo4j` / `""` | — | Reserved. No consumer exists | When a server is available |
| `RLA_LOG_LEVEL` | `INFO` | — | **Currently unused.** The setting is declared in `config.py` but nothing reads it; `config.py` deliberately sets up no logging because it is imported by `rla doctor --help` | Not yet — use an event-level filter or wire it up |

Every field is validated by pydantic with explicit bounds (`ge`/`le`), so an out-of-range value
fails at startup with a message naming the field, rather than producing a strange rate later.

### 4.2 Constants (source, not config)

| Constant | Value | Where | The rule behind it | To change it |
|---|---|---|---|---|
| `PIPELINE_PHASES` | 10 phases | `events.py` | The TUI renders one slot per phase; the order is the product's contract | Edit the tuple, then fix the frame tests |
| `SNOWBALL_SEEDS` | `6` | `acquisition.py` | Seeds for 1-hop snowballing, taken as the most-cited papers | More seeds ⇒ denser citation graph, more requests |
| `SNOWBALL_PER_DIRECTION` | `12` | `acquisition.py` | Fan-out per direction (refs / citations) per seed | Raising it multiplies requests by 2 |
| `PER_QUERY_LIMIT` | s2 25, openalex 25, arxiv 20, dblp 20, crossref 15, serpapi 20 | `acquisition.py` | Per-source request budget per query; S2 is the tightest anonymously | Per source, because the ceilings differ |
| `BATCH_SIZE` | `10` | `scoring.py` | Papers per relevance-scoring call. 100 individual calls would be slow and pointlessly expensive for a judgement used only to trim | Larger batches = fewer calls, worse per-paper attention |
| `CANDIDATE_MULTIPLE` | `3` | `acquisition.py` | How many candidates per paper of corpus cap the scorer may see. Scoring cost must scale with the corpus being *kept*, not with whatever the sources returned | Raising it scores a wider net at proportionally more requests |
| `MIN_KEEP_SCORE` | `3` | `scoring.py` | Papers scoring below 3 are dropped | Loosening admits tangential work |
| `DEFAULT_SCORE` | `3` | `scoring.py` | Unscored papers default to 3 — one failed batch must not empty the corpus. Also the reason a uniform histogram of 3s means "scoring did not run" | A different default changes what a degraded run keeps |
| `MAX_BODY_CHARS` | `4000` | `extraction.py` | Abstract truncation; bounds cost without losing the point | Raise for richer extractions, pay in tokens |
| `MAX_REPORTED_PER_REASON` | `3` | `extraction.py` | Identical failures reported once, then counted. A hundred copies of the same 401 teaches nobody and buries the run | Higher = noisier logs |
| `AUTO_MERGE` | `0.92` | `resolve.py` | Cosine at/above which two clusters are the same thing without asking. Deliberately strict | Lower ⇒ more merges, more risk of fusing a lineage path away |
| `MAYBE_MERGE` | `0.70` | `resolve.py` | Below this they are certainly different; only the band between is judged | Narrowing the band saves judge calls |
| `MAX_JUDGE_CALLS` | `40` | `resolve.py` | Judging is the only per-pair spend; capped, most-similar first, and the cutoff is reported as a warning | Raising it costs quota directly |
| `DESCRIPTION_CHARS` | `200` | `resolve.py` | Representative text for embedding and judging | Longer = more signal, more tokens |
| `STRUCTURAL_GAP_MIN_AGE` | `3` years | `gaps.py` | A concept must predate the corpus by 3 years before its silence counts as abandonment. A direction cannot be called abandoned on a corpus spanning two years — then almost everything looks unbuilt-upon, which is a statement about the corpus, not the field | Corpus-span-relative on purpose; do not make it calendar-absolute |
| `_SATURATION_AT` | `5` | `gaps.py` | A gap is ranked down once 5 papers say the same thing: repetition is evidence the problem is real, not evidence it is open | Higher favours consensus over novelty |
| `THEME_RULES` | 8 themes | `gaps.py` | Keyword clustering, deliberately **not** embeddings: an embedding cluster would cost one request per limitation and the free tier allows ~20/day | Add a theme by adding keywords |
| `_CLOSURE_MARKERS` | 10 phrases | `gaps.py` | A gap is suppressed only when a strictly newer in-corpus paper carries an explicit closure marker **and** shares ≥2 content words | Requiring the marker stops shared vocabulary silently erasing an open problem |
| `DEFAULT_QUERY_COUNT` | `4` | `query_expansion.py` | Target number of sub-topic queries (spec says 3-5); hard-capped at 8 by the schema | More queries = more requests per source |
| `EVAL_QUESTIONS` | 12 | `run_eval.py` | The lineage/gap questions scored by the harness | Broader coverage |
| `DEFAULT_TOP_K` | `5` | `run_eval.py` | Papers retrieved per arm, so both arms retrieve the same amount | Retrieval depth |
| `MATCH_THRESHOLD` | `3.0` | `gap_validity.py` | Held-out paper must score above this to count as addressing a gap | Sensitivity of the gap check |
| `MIN_LATER_YEARS` | `1` | `gap_validity.py` | A held-out paper must be strictly later than the gap to close it | Correct by construction; stated for clarity |
| `TARGET_PAPERS` | `20` | `ground_truth.py` | Hand-labelled reference set size (§10.1) | More labels = narrower error bars |
| `MODEL_PRICING` | per-model USD/1k | `store/cache.py` | Cost estimation. A configured model with **no** price is a test failure, because it silently understates spend | Add the model |
| `MAX_LOG_LINES` | `500` | `tui/state.py` | TUI log buffer | A longer transcript, more memory |
| `TICK_SECONDS` | `0.5` | `tui/app.py` | Elapsed-clock refresh | Slower ticks free CPU; faster ticks cost frames |
| `DEFAULT_LLM_RPM` | `15` | `llm/retry.py` | Library default when no settings object supplies one | Match `RLA_LLM_RPM` |
| `_RETRYABLE_STATUS` | 408, 429, 5xx | `llm/retry.py` | Statuses worth retrying. 400/401/403/404 are the caller's fault and fail identically forever | Very rarely |
| `_PERIOD_QUOTA_MARKERS` | 6 markers | `llm/error_map.py` | Distinguishes a daily cap from a burst 429 | Add a marker if the provider renames its quota id |
| `_RETRYABLE` / `_FALLBACK_ELIGIBLE` | 4 categories each | `llm/errors.py` | **The** error policy. Derived from the category, never re-decided per call site | Extend deliberately, and extend the tests |

### 4.3 Changing something safely

1. **Configuration first.** Anything with a `RLA_` prefix is meant to be changed without code.
   Add new keys to `.env.example` when you add settings — that file is the documented contract.
2. **Constants need their test.** Every constant above is pinned by a test; change the constant and
   the assertion together, and expect to read the assertion to check you agree with the new value.
3. **Prompts invalidate their own cache.** `llm/prompts/templates.py` is hashed into the LLM cache
   key, so editing a prompt re-issues exactly the calls that used it and nothing else. There are no
   prompt *files* — it is a `.py` module on purpose.
4. **Paths resolve from the package, not the CWD.** `config.py` resolves `.env` and `data/` relative
   to `parents[2]`, so the CLI works from any directory.

---

## 5. Recipes

### Why a run stops at "daily free-tier quota exhausted"

Diagnosed 2026-10-01 against a live run. **This is mostly a tier limit, plus four code defects
that made it much worse. All four are now fixed; the tier limit is not.**

**The measured limit.** A live probe on this key returns:

```text
quotaId:    GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: '20'
retryDelay: '53s'
```

**20 requests per day, per project, per model.** Both `gemini-2.5-flash` and
`gemini-2.5-flash-lite` are capped independently, and
`gemini-embedding-001` has its own bucket (still available).

**What the run spent it on.** A 291-paper candidate pool with a 30-paper cap:

| | requests |
|---|---|
| relevance scoring, before the fix | **30** batches → 17 succeeded, the day's allowance gone |
| relevance scoring, after the fix | **9** batches (a 90-paper candidate window) |
| extraction | **30** calls needed, 1 per paper |

Scoring 291 papers to keep 30 spent the entire flash-lite allowance on 261 papers that were then
discarded, leaving nothing for extraction — the stage that actually builds the graph. **That was the
dominant waste, and it is fixed:** `candidate_window()` pre-selects `target_corpus_max × 3` papers
using metadata completeness and citations, so scoring cost now scales with the corpus rather than
with whatever the sources returned.

**The arithmetic that does not go away.** 9 scoring + 30 extraction = 39 requests against a cap of
20. A 30-paper corpus therefore needs **2 days** on one Gemini model, however well the code behaves.
That is arithmetic, not a bug.

**Three defects fixed, each with a test:**

1. **The quota category was lost between the retry layer and the router.** `call_with_retry`
   recognised the daily cap, then re-raised its own *text-only* message. A bare `LLMError`
   normalises to `UNKNOWN`, which is neither retried nor fallen back from — so
   `RLA_FALLBACK_ON_QUOTA=1` could never fire. The documented escape hatch was dead code, and you
   had a fallback model configured (`ling-3.0-flash-sante:free`) that could never be reached.
   Fixed: `retry.py` now raises `ProviderQuotaExhausted`, which is a subclass of `LLMError`, so
   existing handlers are unaffected and the category survives.
2. **The orchestrator pinned `strong_model` for extraction and resolution.** An explicit `model=`
   beats the stage's configured role in the router, so `RLA_STRUCTURED_MODEL` never reached the two
   stages that matter most — you could not move extraction onto a model that still had quota by
   configuration alone. Fixed: the orchestrator passes `settings.model_for_structured`.
3. **A self-hosted model could not be used at all.** See below.

**What is not a bug.** `traverse  no question supplied` and `answer  no question to answer` are
correct: the run was `rla tui -t "Graph Neural network"` with no `-q`. Traversal needs a question.
Add `-q "How did GAT evolve?"` and both phases run.

### Using a local model as an unlimited provider

Scoring, extraction and resolution are all schema-constrained stages. Two things blocked a local
model before:

- **The capability gate refused it.** `litellm.supports_response_schema()` returns `False` for any
  model LiteLLM has no static entry for — including a self-hosted Ollama/llama.cpp server that
  honours `response_format` fine. So every structured stage raised `ProviderUnsupported` without
  sending a request.
- **That answer is not even stable.** It returns different values depending on what earlier code in
  the process already touched. A gate whose input flips with import order is not a gate.

Both are addressed by an explicit operator assertion, which keeps ADR-004's refusal as the default:

```dotenv
RLA_STRUCTURED_OUTPUT_MODELS=qwen3:4b
```

Substring-matched against both `qwen3:4b` and `openai/qwen3:4b`. Empty ⇒ the gate behaves exactly as
before.

**Full local setup** (Ollama, verified end-to-end against `localhost:11434`):

```powershell
ollama serve
ollama pull qwen3:4b          # or: ollama create mymodel -f Modelfile
```

```dotenv
RLA_LLM_PROVIDER=litellm
RLA_FAST_MODEL=openai/qwen3:4b
RLA_STRUCTURED_MODEL=openai/qwen3:4b
RLA_ANSWER_MODEL=openai/qwen3:4b
RLA_STRUCTURED_OUTPUT_MODELS=qwen3:4b
RLA_LLM_BASE_URLS={"openai": "http://localhost:11434/v1"}
RLA_LLM_DAILY_BUDGET=0
```

Two things to know:

- **Keep `GEMINI_API_KEY` set** even if every text call is local. `build_client` returns `None`
  without it, and the pipeline would degrade — and Gemini is still the only wired *embedder*, so
  entity resolution needs it regardless.
- **Verify with `rla doctor --llm`** after switching. It probes the configured backend, so a green
  answer means the local path really served the request.

### Fresh clone → a cited answer

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"
Copy-Item .env.example .env          # then paste GEMINI_API_KEY
rla doctor --llm                     # green means a request went out *now*
rla sources                          # which indexes answer today
rla run -t "Graph Attention Networks" -q "How did GAT evolve?"
```

`python -m src.rla.cli` does **not** work — src layout, import name `rla`. If you have not installed,
use `$env:PYTHONPATH="src"; python -m rla.cli`.

### Recovering from a stale `data/extractions.jsonl`

The graph currently on disk has **zero** `INTRODUCES`/`USES`/`HAS_LIMITATION` edges, because the
committed extraction store and the committed corpus share zero paper ids, and
`store/graph_store.py:add_relations` silently skips any relation whose endpoint is not in the graph.
Every concept consequently has `first_seen_year: null`, which is why `rla report` finds no
structural gaps and `rla ask` says it cannot order the lineage chronologically.

Detect it — the graph report carries the signal:

```powershell
rla run -t "Graph Attention Networks" --jsonl |
  jq 'select(.phase=="graph") | .payload | {extractions, papers_without_extraction: (.papers_without_extraction|length)}'
```

Fix it, cheapest first:

```powershell
# 1. Point the project at the corpus the store belongs to, if you still have it
#    (extraction resume is content-hash keyed, so matching papers cost nothing)

# 2. Or archive the store and re-extract. Extraction resumes by content hash,
#    so re-running never re-calls the model for a paper already stored.
Move-Item data\extractions.jsonl data\extractions.jsonl.bak
Move-Item data\concepts.json   data\concepts.json.bak
rla run -t "<topic>"            # SCORE -> EXTRACT -> RESOLVE -> GRAPH

# 3. Verify
rla stats                        # nodes_Paper should equal the corpus; look for edges_INTRODUCES
```

A guard worth adding later: raise a `warn` event when `papers_without_extraction == all papers`.

### Running on a paid key, at full corpus size

```dotenv
RLA_TARGET_CORPUS_MIN=40
RLA_TARGET_CORPUS_MAX=100
RLA_LLM_DAILY_BUDGET=0          # no local cap
```

`RLA_STRUCTURED_MODEL` on the cheap tier unless you have paid quota — see §3.4 for which stages
actually honour it.

### Adding a second provider

```dotenv
GEMINI_API_KEY=...
OPENAI_API_KEY=...
RLA_LLM_PROVIDER=litellm        # optional; the native path works with one provider
RLA_FALLBACK_MODELS=openai/gpt-4o-mini
RLA_LLM_BASE_URLS={"openrouter": "https://openrouter.ai/api/v1"}
```

`RLA_LLM_BASE_URLS` is a **map, not a single URL**, because during cross-provider failover two
providers are live at once and a shared endpoint would silently break the primary. Keys are the same
provider prefix used in model strings, so `openrouter/meta/llama-3` picks up the `openrouter` entry.
An absent key means "use the provider's default endpoint", which is what you want for `openrouter`
and `groq`. Malformed JSON is ignored with one warning rather than stopping the pipeline. This
applies to the **LiteLLM path only** — the native Gemini backend talks directly to Google.

The credential sent is the one that provider reads, so the entry above sends `OPENAI_API_KEY`.
Declaring a custom OpenAI-compatible server *as* `openai` is the supported way to reach it:

```dotenv
RLA_LLM_BASE_URLS={"openai": "http://localhost:8000/v1"}
RLA_FALLBACK_MODELS=openai/my-local-model
```

An invented prefix like `local` is rejected by LiteLLM with `LLM Provider NOT provided` **before any
request goes out**.

---

## 6. Behaviour you will notice, and why

| What you see | Why it is like that |
|---|---|
| `Extracting 30 papers (0 already extracted)` on a re-run | Extraction resume is keyed on **paper content hash**. Edit an abstract and that one paper is re-extracted; leave it alone and nothing is. |
| `stopping after N extracted: the request allowance is spent` | Both the local budget and the provider's daily ceiling end the batch. Everything extracted so far is on disk, and the message says how to resume. |
| `0/30 papers` in extraction with a valid key | The free tier's per-model daily cap. `rla doctor --llm` distinguishes "bad key" from "quota spent". |
| `no LLM configured, searching the raw title only` | Acquisition is keyless by design; the pipeline degrades rather than aborting. |
| `query expansion failed, falling back to the raw title` | Same reason, per-stage. One query is issued instead of 3-5, which is a coverage loss worth noticing. |
| `Scored 0/N papers - every paper kept the default score of 3` | Explicitly reported, because a uniform histogram of 3s means scoring did **not** run, which otherwise looks like a neutral result. |
| `judge budget reached (40 calls)` | The bounded cost on the only per-pair spend in resolution. Pairs beyond it are left unmerged rather than guessed. |
| `dropped unsupported citation id(s): P47` | The post-generation validator. A prompt forbids inventing ids; a prompt is a request, not a guarantee. |
| `stripped 1 unsupported citation(s): P47` (from `rla ask`) | The same validator, reported after the answer rather than inline. |
| `no gap could be grounded in this corpus` | Both signal sources are empty: no stated limitations, and no concept old enough to be "abandoned". |
| `NOT MEASURED` in `rla eval` | The reference set is 0% hand-labelled, and the harness refuses to score against it. This is a feature — see `PLAN.md` P8. |
| `LLM Provider NOT provided` | LiteLLM does not recognise that prefix. Use a real provider name. |
| `the TUI needs Textual` | The `tui` extra is optional: `pip install -e ".[tui]"`. |
| `rla ask` says "no graph at …" | `data/graph/` is gitignored. Run `rla run -t "<topic>"` first. |
| `rla eval` crashes with `FileNotFoundError` | Same cause. |
| Tests fail with odd model/provider names | Tests pin their own routing config so the developer's `.env` cannot leak into them. |
| System Python fails to collect `test_p1_acquisition.py` | `respx` is missing there. Use `.\.venv\Scripts\python.exe`. |

---

## 7. Development

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q              # 529 passed in ~68s
.\.venv\Scripts\python.exe -m ruff check src/ tests/        # All checks passed
.\.venv\Scripts\python.exe -m pytest tests/test_p9_provider_routing.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -k fallback
```

Test modules are named `test_p<N>_*.py` after the `PLAN.md` milestone they gate, not after the
module under test — so `test_p5_traversal.py` and `test_p6_gaps.py` live side by side in
`tests/`. `pyproject.toml` sets `asyncio_mode = "auto"`, so there are no `@pytest.mark.asyncio`
markers.

`tests/conftest.py` redirects every path to `tmp_path`, zeroes `s2_delay_seconds`, and sets
`max_retries=1`, so the suite never touches `data/`. `rla.llm.retry` keeps a process-global
limiter and spender keyed to the running event loop; use `reset_limiter()` / `reset_spender()`
between tests that call `asyncio.run` repeatedly.

Two structural tests are worth knowing about, because they are the guards rather than the
behaviour:

- `test_a1_no_pipeline_module_imports_a_provider_sdk` — walks the AST of every module outside
  `llm/` and fails on any provider SDK import. This is what makes a provider swap a config change.
- `test_a6_a_cache_hit_prevents_any_provider_call` — the PLAN P1 gate, asserted at the level of an
  actual call counter for both structured and streamed calls.