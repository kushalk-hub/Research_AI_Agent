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
rla --help          # all 12 commands
```

**Expected:** `doctor` lists 5 keyless sources enabled, SerpApi marked `disabled`, and
prints *"LLM stages will not run without a key"* if `GEMINI_API_KEY` is blank.

---

## 2. Check the live LLM connection ⚠️ needs quota

```powershell
rla doctor --llm
```

Probes every configured model with a real request. **Costs 3 requests** (structured, answer,
embedding — see `_probe_plan` in `src/rla/cli.py`) and is deliberately uncached, so a green light
means a request went out *now*.

**Verified 2026-10-01: green.** `structured gemini-2.5-flash-lite ok`, `answer
gemini-2.5-flash ok`, `embedding gemini-embedding-001 ok (3072 dims)`. The free tier allows
~20 requests per model per day, so this goes red again once the daily allowance is spent —
that is the expected state, and it is different from a bad key.

---

## 3. Check the source APIs (network, no key)

```powershell
rla sources
```

Probes Semantic Scholar, OpenAlex, arXiv, DBLP, CrossRef against a throwaway cache and
reports which are live. Worth running before a build: a source behind bot protection
otherwise fails silently as "zero results".

---

## 4. Build without a question (network; keyless = acquisition only) ✅ works now

```powershell
rla build -t "Graph Attention Networks"
```

`build` is the full pipeline **without a question**: acquisition → extract → resolve →
graph; the `traverse`/`answer` phases are skipped because no question was supplied.
Keyless (no `GEMINI_API_KEY`), it stops after acquisition — extraction needs an LLM, so
there are no concepts to graph.

Fans out across all sources, dedupes by DOI and title, and writes `data/corpus.json`.
Takes a minute or two. Prints per-source yield.

**Verified on this machine:** the corpus cap in `.env` is `RLA_TARGET_CORPUS_MIN=15` /
`RLA_TARGET_CORPUS_MAX=30`, so a build yields **30 papers, 30 abstracts, 30 years, 29 DOIs**
(per-source yield: Semantic Scholar 25, OpenAlex 25, arXiv 20, CrossRef 15; DBLP contributes 0 —
it is behind bot protection, and `rla sources` says so). Raise the two settings to 40/100 for the
spec's original 40-100 range.

---

## 5. Full pipeline, live event stream (network) ✅ works now

```powershell
rla run -t "Graph Attention Networks"
```

The headline demo. Every stage emits a line as it happens — `search`, `fetch`, `score`,
`fulltext` (pending stub), `extract`, `resolve`, `graph`, `traverse`, `answer`, `done`.

Add a question to also get an answer:

```powershell
rla run -t "Graph Attention Networks" -q "How did attention over graphs evolve?"
```

Machine-readable, for piping into jq or a log:

```powershell
rla run -t "Graph Attention Networks" --jsonl
```

**Verified 2026-10-01:** completes end to end and builds a real graph, with all 30 papers
carrying relevance scores 3/4/5, so the LLM scoring stage genuinely ran. Graph counts are
`rla stats` as of 2026-10-02 — the graph is local (`data/graph/` is gitignored), so run
`rla stats` for your own numbers: `192 nodes (30 papers, 162 concepts), 140 edges (20 CITES,
120 derived)`.

> **Caveat on this machine's committed data.** `data/extractions.jsonl` and `data/corpus.json`
> currently describe **different corpora** (verified 2026-10-02: `rla status` reports 0 matched,
> 26 stale, 30 missing — zero shared paper ids), and `add_relations` silently skips relations
> whose endpoint is absent. The visible symptom depends on what was last built: missing
> `INTRODUCES`/`USES` edges, `first_seen_year: null` concepts, or a graph `rla status` flags as
> stale. Run `rla status` for the current agreement. Recovery recipe:
> [`OPERATIONS_GUIDE.md`](OPERATIONS_GUIDE.md) §5. Fix it before demoing lineage.

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

**Verified 2026-10-01:** classifies LINEAGE, streams a cited answer naming `[C5]`, `[C11]`,
`[C14]` and others, and correctly self-reports the one thing it cannot do — order the chain
chronologically — because concept years were null in the graph that run built (the local graph
has changed since; `rla stats` / `rla report` show today's state).

**Five** question types map to different traversals — lineage, gap, comparison, approaches,
full-report. `rla ask` classifies automatically from keywords; the traversal is pure code, no model
needed.

---

## 7. Limitations and synthesized gaps (no key) ✅ works now

```powershell
rla report
rla report --jsonl        # machine-readable
```

Reads the corpus and stored extractions, no LLM calls. **As of 2026-10-02: 26 papers
analysed, 0 stating a limitation, 0 themes, 48 structural gaps.** The zero-limitation half is
a real finding about the current extraction store (every stored `stated_limitation` is empty),
not a failure. Structural gaps come from concept `first_seen_year` values in the local graph,
so re-run `rla report` for live numbers. See `PLAN.md` P2/P4 before presenting this as a demo
of gap analysis.

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
Keys: `q` quit, `c` clear log, `m` toggle the model selector, `e` cycle the
structured-role model, `a` cycle the answer-role model, `x` clear session
overrides, `?` help overlay.

**Requires Windows Terminal**, not legacy conhost. Needs the `tui` extra.

---

## 10. Developer commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q               # 668 tests, ~80s
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
3. `rla stats` — the corpus is already built and committed (30 papers at the current cap).
4. `rla run -t "Graph Attention Networks"` — the event stream building a real graph.
5. `rla stats` again — node and edge counts went from nothing to 192 nodes / 140 edges
   (measured 2026-10-02; run `rla stats` for the current local graph).
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
