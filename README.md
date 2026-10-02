# rla — Graph-Based Research Literature Agent

Ingests papers on a research topic, builds a citation-and-concept graph, and traverses
that graph to answer lineage questions ("how did technique X evolve?") and gap questions
("what's still unsolved in Y?") with traceable citations.

This README is an operational document: how to install, configure, verify, run, and
diagnose `rla`. Design rationale lives in `docs/` and the ADRs (see Documentation map);
this file links to those rather than duplicating them.

> **Entry point:** the `rla` console script. `python -m src.rla.cli` does **not** work
> (src-layout package; the import name is `rla`).

---

## Requirements

- Windows, PowerShell.
- Python 3.11+ (verified on 3.12).
- For the TUI: **Windows Terminal** (not legacy conhost) and the `tui` extra.
- For fully-local mode: a running Ollama server (see Ollama setup).
- For cloud stages: a Gemini API key (see Gemini setup). Without one, the pipeline
  runs in keyless degrade mode.

## Installation (fresh Windows machine)

```powershell
git clone <repo-url>
Set-Location Research_AI_Agent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"
Copy-Item .env.example .env
```

Use the venv's tools for everything below (`python`, `pytest`, `ruff` from
`.venv\Scripts\`). The system Python may lack test deps and ships an older `ruff`
that reports false hits.

## Repository setup

Clone first (see Installation above), then note: `data/graph/` is gitignored, so a fresh clone has **no graph**. Run `rla run` or
`rla build` before `rla eval` / `rla ask` (both fail with `FileNotFoundError` /
"no graph" otherwise).

## Environment configuration

1. Copy the template: `Copy-Item .env.example .env`
2. Fill in what your mode needs (see Supported modes). `.env` is gitignored;
   never put a real key in `.env.example`.
3. All variables use the `RLA_` prefix **except** `GEMINI_API_KEY`, which has an
   explicit no-prefix alias (`src/rla/config.py`). Paths (`.env`, `data/`) resolve
   relative to the repo root, not the CWD, so running from a subdirectory is safe.

Full variable list: [Config reference](#config-reference) and `.env.example`.

## Supported modes

Only these three configurations are supported by the code:

| Mode | Text models | Embedding model | Needs `GEMINI_API_KEY`? |
|---|---|---|---|
| Fully local | `ollama/…` in all roles | `ollama/nomic-embed-text` (768 dims) | No |
| Ollama + cloud hybrid | `ollama/…` for text | Gemini embedder | Yes (embeddings still go through Gemini) |
| Cloud / fallback | Gemini (native) or second provider via LiteLLM `[router]` extra | `gemini-embedding-001` | Yes |

With a blank `GEMINI_API_KEY` and no usable `ollama/…` role, the pipeline runs in
keyless degrade mode: acquisition works, LLM stages are skipped.

## Ollama setup

```powershell
ollama serve
ollama pull qwen3:4b
ollama pull nomic-embed-text
```

```dotenv
RLA_FAST_MODEL=ollama/qwen3:4b
RLA_STRUCTURED_MODEL=ollama/qwen3:4b
RLA_ANSWER_MODEL=ollama/qwen3:4b
RLA_EMBEDDING_MODEL=ollama/nomic-embed-text
RLA_OLLAMA_URL=http://localhost:11434
RLA_LLM_DAILY_BUDGET=0
```

Notes (verified, `docs/OPERATIONS_GUIDE.md` §5):

- The native backend talks to `/api/generate` (endpoints used: `/api/generate`,
  `/api/embed`). Never route `ollama/…` models through LiteLLM's `/v1` path —
  the same schema measured ~8 s native vs ~98 s via LiteLLM. That gap is
  compatibility/prefill overhead (~4096 vs ~662 prompt tokens), **not** intrinsic
  generation speed (decode floor ~55 tok/s).
- `RLA_OLLAMA_URL` takes no `/v1` or `/api` suffix; the backend appends the path.
- `RLA_OLLAMA_THINK=false` (default): reasoning-model thinking traces stay off.
- Fully-local mode needs an `ollama/…` model in the roles (then no Gemini key is
  needed at all).

## Gemini setup

```dotenv
GEMINI_API_KEY=your-key-here
```

- Get the key from [Google AI Studio](https://aistudio.google.com/apikey). Use an
  AI Studio key, not `gcloud auth print-access-token` output (OAuth tokens return
  401; `rla doctor --llm` says so).
- Canonical answer model: `gemini/gemini-2.5-flash`. The configured model must be
  servable on your key — a 404 means retired/renamed/tier-gated, so pick a current
  model in `.env`.
- Never print or commit real keys. `rla doctor --llm` performs live (deliberately
  **uncached**) probes and spends a few requests.
- Free-tier quota is per day, per model (~20 req/day observed). `llm_rpm` pacing
  does not help; `llm_daily_budget` (default 15) is a local per-run cap.

## Embedding config

- The text model and the embedding model are different settings. Defaults:
  `RLA_EMBEDDING_MODEL=gemini-embedding-001` (GA replacement for retired
  `text-embedding-004`), or `ollama/nomic-embed-text` (768 dims) for fully-local.
- Merge thresholds belong to an embedding space (`thresholds_for()`,
  `docs/adr/0007-per-embedding-model-merge-thresholds.md`). Never reuse 0.92/0.70
  across spaces.
- A new/uncalibrated embedding space starts `UNCALIBRATED`: auto-merge is
  **disabled** (fail toward duplicates, never toward false lineage), borderline
  pairs go to the bounded LLM judge. `rla calibrate-merges` **proposes** a
  threshold; a human commits it. It installs nothing.

## Verify installation

```powershell
rla doctor            # config, sources, cache — no key needed
rla doctor --llm      # live probe of every configured model (spends requests)
rla sources           # probe each source API against a throwaway cache DB
rla events            # the 10 pipeline phases, in order
```

`rla build` / `rla report` are useful with no key at all (acquisition and gap
report are keyless).

## CLI reference

Verified against `src/rla/cli.py`. Prompts interactively for `-t` when omitted (`build`, `run`, `tui`); `ask` takes the question as a positional argument and prompts when omitted.

| Command | What it does | Needs a key? |
|---|---|---|
| `rla doctor [--llm]` | config, sources, cache; `--llm` probes models live (uncached) | `--llm` only |
| `rla sources [--probe "q"] [--cache/--no-cache]` | probe each source API (bypasses cache by default) | no |
| `rla stats` | corpus + graph summary tables | no |
| `rla events` | print the 10 pipeline phases in order | no |
| `rla build -t "Topic" [--jsonl] [--structured-model M] [--answer-model M]` | acquisition only (40–100 papers) | no |
| `rla run -t "Topic" [-q "Q"] [--jsonl] [--structured-model M] [--answer-model M]` | full pipeline, streaming events | degrades without a key |
| `rla ask "Q" [--markdown] [--jsonl]` | answer from the built graph; no re-acquisition | yes, for the answer |
| `rla report [--markdown] [--jsonl]` | per-paper limitations + synthesized gaps; costs no LLM calls | no |
| `rla status [--prune]` | corpus/store/graph agreement; `--prune` deletes stale+superseded | no |
| `rla calibrate-merges` | propose (not install) a merge threshold for the embedding model | yes (embeddings) |
| `rla eval` | evaluation report → `data/eval/report.md` + `results.json` | no |
| `rla tui -t "Topic" [-q "Q"] [--structured-model M] [--answer-model M]` | live terminal UI over the same event stream as `run` | degrades without a key |

Examples:

```powershell
rla sources
rla build -t "Graph-based agent architectures"
rla run -t "Graph-based agent architectures" -q "How did GAT evolve?"
rla run -t "Graph Attention Networks" -q "How did GAT evolve?" --jsonl
rla ask "How did GAT evolve?" --markdown
rla report --jsonl
rla status
rla status --prune
rla eval
```

## TUI guide

Verified against `src/rla/tui/app.py` (`BINDINGS`, `HELP_TEXT`).

```powershell
rla tui -t "Graph Attention Networks" -q "How did GAT evolve?"
```

Requires the `tui` extra and **Windows Terminal** (not conhost). 80×24 works.
The TUI subscribes to the same event stream as `rla run`, so it cannot drift
from headless output. Rule of thumb: debug with `rla run`, demo with `rla tui`.

Panels: status (phase + clock) · counters · routing
(configured/override/resolved) · selector (session only) · log (wraps, no deltas)
· tree · answer (deltas + citations).

| Key | Action |
|---|---|
| `q` | quit |
| `c` | clear log |
| `m` | toggle model selector |
| `e` | cycle structured-role model |
| `a` | cycle answer-role model |
| `x` | clear session overrides |
| `?` | this help overlay |

The model selector offers the two role models plus configured fallbacks
(de-duplicated); cycling sets a transient session override (see next section),
never writes `.env`. Fallback traffic is visible in the UI when the router side
is connected.

## Model selection, routing, fallback

- **Model identity.** Canonical form is `provider/model`. `ollama/qwen3:4b` is
  valid; `gemini/gemini-2.5-flash` is canonical. A bare `qwen3:4b` raises
  `ModelResolutionError` (ambiguous); `foo/bar` raises it (unknown provider).
  Resolution happens before any network request, never a silent guess. Details:
  `docs/OPERATIONS_GUIDE.md` §3.4.
- **Precedence** (highest first): session override (TUI selector or
  `--structured-model` / `--answer-model` flags) > explicit `model=` call-site
  argument > stage role (`answer` → `RLA_ANSWER_MODEL` → `RLA_STRONG_MODEL`;
  structured stages → `RLA_STRUCTURED_MODEL` → `RLA_FAST_MODEL`; other stages →
  `RLA_FAST_MODEL`) > nothing (no heuristics, no load balancing).
- **Fallback** is error-category-driven and distinct from retry: it fires on
  `timeout`, per-minute 429, 5xx, network errors. It does **not** fire on bad
  credentials, malformed config, unsupported schema, or programming errors.
  Daily-quota exhaustion raises rather than failing over unless
  `RLA_FALLBACK_ON_QUOTA=true`. Streaming never falls back mid-stream.
- **Capability gate.** A model is used for a structured stage only if it supports
  schema-constrained output; otherwise the router refuses it rather than
  degrading to unvalidated JSON. Native `ollama/…` grammar-constrains via
  `format:` and needs no declaration. See `docs/OPERATIONS_GUIDE.md` §3.5.
- Multi-backend dispatch: `docs/adr/0006-multi-provider-dispatch.md`.

## Data and status operations

Files each phase writes: `docs/OPERATIONS_GUIDE.md` §1 (corpus, extractions,
concepts, graph, cache, eval outputs).

`rla status` reports per-entry agreement between the corpus, the extraction
store, and the graph:

| State | Meaning | Effect |
|---|---|---|
| matched | entry describes a corpus paper | ok |
| missing | corpus paper has no extraction | warning; graph will be partial |
| stale / superseded | extraction no longer matches the corpus | **blocks** graph builds; prune then re-run |
| graph missing/stale papers | graph disagrees with the corpus | rebuild via `rla run` |

```powershell
rla status            # read-only, no network, no model, no budget
rla status --prune    # delete stale + superseded entries, then re-run `rla run`
rla stats             # corpus + graph summary tables
```

## Common errors

**Python / venv.**

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: No module named 'rla'` | `python -m src.rla.cli` never works (src-layout). Use the `rla` command. |
| `test_p1_acquisition.py` fails to collect | system Python lacks `respx`. Use `.venv\Scripts\python.exe`. |
| `ruff` reports `UP038` hits | system ruff is 0.1.14. Use the venv's pinned `ruff>=0.5`. |

**Ollama.**

| Symptom | Cause / fix |
|---|---|
| connection refused | `ollama serve` is not running; check `RLA_OLLAMA_URL` (no `/v1`/`/api` suffix). |
| structured stages refuse the model | over the LiteLLM `/v1` path the capability gate refuses local models; use native `ollama/…` ids instead. |
| slow extraction (~90 s+/paper) | `ollama/…` routed through LiteLLM `/v1`; switch to native `ollama/…` (`/api/generate`). |
| everything becomes duplicates | new embedding space is `UNCALIBRATED`; run `rla calibrate-merges` and commit a threshold. |

**Gemini (incl. 404).**

| Symptom | Cause / fix |
|---|---|
| 404 / `NOT_FOUND` | configured model retired/renamed/tier-gated — pick a current model in `.env`. `rla doctor --llm` hint: "model retired". |
| 401 on every call | OAuth token instead of an AI Studio key. Replace `GEMINI_API_KEY`. |
| `limit: 0` / `RESOURCE_EXHAUSTED` on Pro models | free tier has no quota there; use a flash-tier model. |
| daily per-model allowance spent | per day, per model (~20 req/day). Use a model with quota left or wait; `RLA_FALLBACK_ON_QUOTA=true` opts into spending the reserve. |

**Model resolution** (exact messages, `src/rla/errors.py` + `src/rla/config.py`):

```text
Ambiguous model id 'qwen3:4b': it names no known provider. Specify an explicit
provider prefix, for example 'ollama/qwen3:4b' (or another supported provider/model id).
```

```text
Unknown provider prefix 'foo' in model id 'foo/bar'. Known providers: anthropic,
azure, bedrock, cohere, deepseek, gemini, groq, mistral, ollama, openai, openrouter, xai.
```

Fix: write the id as `provider/model`. These raise before any request; the router
never retries or falls back on them.

**Embeddings.** Never reuse 0.92/0.70 across embedding spaces. Uncalibrated space
→ auto-merge disabled (safe direction: visible duplicates, never fused lineage).

**Fallback.** Not firing on quota/auth/400s is by design (see previous section).
A failure that "should have failed over" is usually a non-fallback-eligible
category — check the category, not the retry count.

**Integrity.** `rla ask` "no graph" / `rla eval` `FileNotFoundError` → fresh clone
(no `data/graph/`); run `rla run` first. `rla status` red rows → prune + re-run.

**TUI.** Garbled layout → legacy conhost; use Windows Terminal. `the TUI needs
Textual` → `pip install -e ".[tui]"`.

**Diagnosis workflow:** `rla doctor` → `rla doctor --llm` → `rla sources` →
`rla status` → `rla run --jsonl` (inspect per-phase events) → narrow with the
table above.

## Troubleshooting decision flow

```text
rla doctor fails ─▶ venv installed? (.venv\Scripts\python.exe) ─▶ .env present?
rla doctor --llm fails ─▶ 401? bad key ─▶ 404? retired model ─▶ quota? daily cap
sources empty ─▶ rla sources: which index is down? (bot protection / rate limit)
status red ─▶ stale/superseded? --prune + re-run ─▶ missing? re-run extracts them
run stalls at extraction ─▶ quota spent (free tier ~20/day) or hung provider (120 s timeout)
ask/eval "no graph" ─▶ rla run first (data/graph/ is gitignored)
TUI broken ─▶ conhost? use Windows Terminal ─▶ Textual missing? install [tui]
slow local inference ─▶ ollama/… via LiteLLM? switch to native ollama/… ids
false lineage ─▶ over-merge; check embedding-space calibration (ADR-0007)
```

## Useful commands

```powershell
rla doctor --llm
rla sources --probe "graph attention networks"
rla build -t "Graph Attention Networks" --jsonl
rla run -t "Graph Attention Networks" -q "How did GAT evolve?" --jsonl
rla ask "How did GAT evolve?" --markdown
rla report
rla status
rla stats
rla events
rla calibrate-merges
rla eval
rla tui -t "Graph Attention Networks" -q "How did GAT evolve?"
```

## Config reference

`.env.example` is the documented contract — every variable is described there.
Key settings (defaults in `src/rla/config.py`):

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | (blank → degrade mode) | no `RLA_` prefix; AI Studio key |
| `RLA_FAST_MODEL` | `gemini-2.5-flash-lite` | generic fallback; `doctor` probes |
| `RLA_STRONG_MODEL` | `gemini-2.5-flash` | fallback for answer role |
| `RLA_STRUCTURED_MODEL` | (empty → `fast_model`) | 4 schema-constrained stages |
| `RLA_ANSWER_MODEL` | (empty → `strong_model`) | streamed answers |
| `RLA_EMBEDDING_MODEL` | `gemini-embedding-001` | or `ollama/nomic-embed-text` |
| `RLA_FALLBACK_MODELS` | `gemini-2.5-flash` | ordered, comma-separated |
| `RLA_FALLBACK_ON_QUOTA` | `false` | opt into failover on daily quota |
| `RLA_LLM_PROVIDER` | `gemini` | `gemini` \| `litellm` (needs `[router]` extra) |
| `RLA_LLM_BASE_URLS` | (empty) | JSON map `{"provider": "url"}`; LiteLLM path only |
| `RLA_STRUCTURED_OUTPUT_MODELS` | (empty) | operator assertion for LiteLLM-route local models |
| `RLA_OLLAMA_URL` | `http://localhost:11434` | no `/v1`/`/api` suffix |
| `RLA_OLLAMA_THINK` | `false` | reasoning-trace emission |
| `RLA_LLM_RPM` / `RLA_LLM_MAX_RETRIES` | `15` / `5` | pacing is not the quota fix |
| `RLA_LLM_DAILY_BUDGET` | `15` (`0` = uncapped) | local per-run, per-model cap |
| `RLA_LLM_TIMEOUT_SECONDS` | `120` | per provider attempt |
| `RLA_SERPAPI_API_KEY` | (blank → Scholar pass off) | recent-preprint coverage |
| `RLA_TARGET_CORPUS_MIN` / `_MAX` | `40` / `100` | corpus bounds |

## Development and testing

```powershell
python -m pytest tests/ -q                          # 668 passed
python -m pytest tests/test_p8_gap_validity.py -v    # one module
python -m ruff check src/                            # line-length 100, select E,F,I,UP,B
```

`pyproject.toml` sets `asyncio_mode = "auto"` — no `@pytest.mark.asyncio`
markers. Test modules are named `test_p<N>_*.py` after the `PLAN.md` milestone
they gate. Tests redirect all paths to `tmp_path` and never touch `data/`.

## Documentation map

| Document | Covers |
|---|---|
| `docs/OPERATIONS_GUIDE.md` | full operations reference this README summarizes |
| `docs/adr/0006-multi-provider-dispatch.md` | MultiBackend dispatch design |
| `docs/adr/0007-per-embedding-model-merge-thresholds.md` | per-embedding-space merge thresholds |
| `docs/adr/` | all architecture decisions behind the LLM layer |
| `docs/demo_commands.md` | command-by-command manual checks with expected output |
| `docs/env_loading.md` | how `.env` is found and resolved |
| `PLAN.md` | milestones and acceptance gates |
| `AGENTS.md` | conventions and gotchas for coding agents |

## License

See repository history. `research-literature-agent-project-final.md` is the
read-only original specification.
