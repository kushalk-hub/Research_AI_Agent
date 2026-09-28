# Demo & Manual Test Commands

Every command below was run and verified on this machine. Anything that needs a key or
quota is marked, and what you will actually see is stated.

```powershell
# Activate once per shell
.\.venv\Scripts\Activate.ps1
```

---

## 1. Zero-setup sanity checks (no key, no network)

Fastest way to confirm the install is healthy.

```powershell
rla doctor          # config, enabled sources, cache state
rla events          # the 10 pipeline phases, in order
rla stats           # corpus + graph summary
rla --help          # all 10 commands
```

**Expected:** `doctor` lists 5 keyless sources enabled, SerpApi marked `disabled`, and
prints *"LLM stages will not run without a key"* if `GEMINI_API_KEY` is blank.

---

## 2. Check the live LLM connection ⚠️ needs quota

```powershell
rla doctor --llm
```

Probes every configured model with a real request. **Costs 3 requests** (fast, answer,
embedding) and is deliberately uncached, so a green light means a request went out *now*.

**Currently fails on the free tier** — both Gemini models report their daily quota spent.
This is the expected state until the daily reset or a paid key.

---

## 3. Check the source APIs (network, no key)

```powershell
rla sources
```

Probes Semantic Scholar, OpenAlex, arXiv, DBLP, CrossRef against a throwaway cache and
reports which are live. Worth running before a build: a source behind bot protection
otherwise fails silently as "zero results".

---

## 4. Acquire a corpus (network, no key) ✅ works now

```powershell
rla build -t "Graph Attention Networks"
```

Fans out across all sources, dedupes by DOI and title, and writes `data/corpus.json`.
Takes a minute or two. Prints per-source yield.

**Verified on this machine:** 100 papers, 100 with abstracts, 98 with DOIs.

---

## 5. Full pipeline, live event stream (network) ✅ works now

```powershell
rla run -t "Graph Attention Networks"
```

The headline demo. Every stage emits a line as it happens — `search`, `fetch`, `score`,
`extract`, `resolve`, `graph`, `traverse`, `answer`, `done`.

Add a question to also get an answer:

```powershell
rla run -t "Graph Attention Networks" -q "How did attention over graphs evolve?"
```

Machine-readable, for piping into jq or a log:

```powershell
rla run -t "Graph Attention Networks" --jsonl
```

**Verified on this machine:** completes end to end and builds a real graph —
`206 nodes (100 papers, 106 concepts), 323 edges (0 citation, 182 derived)`.

> Because the daily quota is spent, extraction reports `0/100 papers` and resolution
> falls back to name-only. The graph is still built from the corpus. On a paid key the
> same command populates concepts and lineage edges.

---

## 6. Ask a question against the built graph ⚠️ needs quota for the prose

```powershell
rla ask "how did graph attention networks evolve?"
rla ask "what is still unsolved in graph-based agent architectures?"
rla ask "compare message passing and attention for graphs" --markdown
```

Requires `data/graph/graph.json`, so run step 4 or 5 first. Traversal is free and always
runs; the narrative needs a key. Answers stream with `[C5]`-style citations, and any
citation id not in the subgraph is stripped and reported.

**Verified on this machine:** traverses 14 nodes / 20 edges and streams a cited answer.

The four question types map to different traversals — lineage, gap, comparison, overview.
`rla ask` classifies automatically; the traversal is pure code, no model needed.

---

## 7. Limitations and synthesized gaps (no key) ✅ works now

```powershell
rla report
rla report --jsonl        # machine-readable
```

Reads the corpus and stored extractions, no LLM calls. **Currently reports 26 papers
analysed, 0 stating a limitation** — a real finding about the current extraction store,
not a failure. Depends entirely on what has been extracted.

---

## 8. Evaluation (no key) ✅ works now

```powershell
rla eval
```

Writes `data/eval/report.md` and `data/eval/results.json`.

**Current output, honestly:** the graph-vs-RAG comparison shows `not comparable`, gap
validity says `no gaps were available to check`, and extraction accuracy is
`NOT MEASURED` because the shipped reference set has 0% hand-labelled items.

**That is the intended behaviour.** The harness refuses to report a number it cannot
measure — see `docs/llm_architecture_audit.md`. A demo should present this as a feature.

---

## 9. Terminal UI (network)

```powershell
rla tui -t "Graph Attention Networks"
rla tui -t "Graph Attention Networks" -q "How did GAT evolve?"
```

Live status strip, colour-coded event log, traversal tree, streamed answer panel.
Keys: `q` quit, `c` clear log.

**Requires Windows Terminal**, not legacy conhost. Needs the `tui` extra.

---

## 10. Developer commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q               # 508 tests, ~70s
.\.venv\Scripts\python.exe -m ruff check src/ tests/         # lint

# focused
.\.venv\Scripts\python.exe -m pytest tests\test_p9_provider_routing.py -v
.\.venv\Scripts\python.exe -m pytest tests\ -k fallback
.\.venv\Scripts\python.exe -m pytest tests\ -k base_url
```

Use the venv's tools, not `PATH`. The system Python lacks `respx` and has an older `ruff`
that reports failures the pinned version does not.

---

## 11. Showcasing the provider routing

The routing layer is the newest work and the most interesting to demo.

```powershell
# which provider, which models, which fallbacks
rla doctor

# prove the LiteLLM path is live (needs litellm installed + quota)
.\.venv\Scripts\python.exe -m pip install -e ".[router]"
$env:RLA_LLM_PROVIDER="litellm"
rla doctor --llm

# route a specific stage to a different model
$env:RLA_STRUCTURED_MODEL="gemini-2.5-flash"
rla run -t "Graph Attention Networks" -q "How did GAT evolve?"

# point a provider at a custom endpoint
$env:RLA_LLM_BASE_URLS='{"openai":"http://localhost:8000/v1"}'
$env:RLA_FALLBACK_MODELS="openai/my-local-model"
rla doctor --llm
```

See `docs/llm_provider_migration_plan.md` for the design and
`docs/llm_provider_validation.md` for what was actually verified live.

---

## 12. Suggested demo script (3 minutes)

1. `rla doctor` — show the provider, models, and that it degrades without a key.
2. `rla sources` — show which academic APIs actually respond right now.
3. `rla stats` — the corpus already has 100 papers committed.
4. `rla run -t "Graph Attention Networks"` — the event stream building a real graph.
5. `rla stats` again — node and edge counts went from nothing to 206/323.
6. `rla ask "how did graph attention networks evolve?"` — a cited answer streaming in.
7. `rla report` — limitations and gaps, with no model calls at all.
8. `rla eval` — and the point: it reports `NOT MEASURED` rather than inventing a number.

Steps 3, 7 and 8 work with **no API key and no quota**, so the demo cannot dead-end
halfway.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'rla'` | editable install lost | `.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"` |
| `daily free-tier quota exhausted` | ~20 req/model/day used up | wait for reset, or use a paid key |
| `rla ask` says "no graph at ..." | step 4/5 not run yet | `rla run -t "<topic>"` |
| `LLM stages will not run without a key` | `GEMINI_API_KEY` blank | add it to `.env` |
| `tui` renders wrong | legacy conhost | use Windows Terminal |
| extraction reports `0/N papers` | quota or missing key | `rla doctor --llm` to confirm |
| tests fail on model/provider names | `.env` leaking into tests | should not happen; tests pin their own config |
