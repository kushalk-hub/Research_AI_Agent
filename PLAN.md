# PLAN — Research Literature Assistant Agent

An intelligent agent that takes a **research project title**, ingests relevant papers, builds a
**citation-and-concept graph**, and traverses that graph to answer *lineage* questions
("how did technique X evolve?") and *gap* questions ("what's still unsolved in Y?") with traceable
citations.

Derived from [`research-literature-agent-project-final.md`](research-literature-agent-project-final.md).
Section numbers below in the form (§N) refer to that spec.

> **Operational guide:** how to actually run every feature, how model routing works, and where
> every limit lives is [`docs/OPERATIONS_GUIDE.md`](docs/OPERATIONS_GUIDE.md). Command-by-command
> manual checks are in [`docs/demo_commands.md`](docs/demo_commands.md). This file is the
> authoritative record of **what is built and whether each target was achieved**.

---

## 0. Status at a glance

Status re-verified against the working tree on **2026-10-01**: `529 passed in 68s`, `ruff: All
checks passed`, `rla doctor --llm` reports all three configured models reachable, and a live
`rla ask` returned a cited lineage answer.

| Milestone | Verdict | One-line evidence |
|---|---|---|
| P0 Foundation | **achieved** | Every command runs; a cache hit provably makes zero provider calls. |
| P1 Acquisition | **achieved** | Live corpus: 30 papers, 30 abstracts, 30 years, 29 DOIs, 0 duplicate DOIs, relevance scores 3/4/5 (so the LLM filter really ran). |
| P2 Extraction | **partially achieved** | 26/26 live extractions parsed (100%). **0/26 produced a stated limitation**, so the gap half of the product has no input. |
| P3 Entity resolution | **partially achieved** | LLM judge ran live; 41 decisions logged with evidence. **The gate's own assertion fails**: "GAT" and "graph attention networks" are still 4+ separate nodes. |
| P4 Graph construction | **achieved** | Live graph 135 nodes / 104 edges, zero temporal violations, `.json` + `.graphml` round-trip. |
| P5 Traversal + answers | **achieved** | All 5 strategies implemented; live `rla ask` streamed a cited answer and self-reported the missing years. |
| P6 Gap analysis | **implemented, no live output** | Code path is complete and tested; with 0 stated limitations and 0 concept years it renders "no gap could be grounded". |
| P7 Orchestrator + TUI | **achieved (automated)** | 80×24 composed-frame tests green; the literal Windows Terminal visual check is still a human step. |
| P8 Evaluation | **harness only** | `rla eval` runs and refuses to invent numbers. **No metric is actually measured** — see P8. |
| P9 Provider routing | **achieved** | Provider is an env var; capability gate, fallback, usage accounting and 1-command provider swap all tested and validated live on Gemini. |
| P10 Per-provider base URLs | **achieved** | `RLA_LLM_BASE_URLS` map, prefix resolution, malformed-JSON tolerance. |
| P11 Readable answer failures | **achieved** | `rla ask` turns a multi-KB provider blob into a category + one actionable sentence. |
| P12 Multi-provider + local inference | **achieved** | Cross-provider dispatch via `MultiBackend`; native Ollama text + embeddings; per-space merge thresholds; fully local run with no Gemini key. Benchmark, not a gate: 8.1 s native vs 97.6 s via LiteLLM. |
| P9 (original) Polish items | **partially achieved** | README, demo script, architecture notes done. **No** architecture diagram, **no** Neo4j import script, **no** D3 export. |
| Phase 2 full text | **not started** | `FULLTEXT` is a phase slot with a `pending` event and no implementation behind it. |

**Headline:** the five-layer architecture in §2 of the spec is fully implemented end to end and
runs live. Two of its outputs are empty for a data reason, not a code reason — the extraction stage
returns no stated limitations, and the concept layer carries no publication years. Everything else
in the spec that was in scope for an MVP exists.

**On the daily-request budget.** Measured live on 2026-10-01, this key is on
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` with `quotaValue: 20` — **20 requests per day,
per project, per model**. A 30-paper corpus needs 30 extraction calls, so it cannot complete in one
day on a Gemini model regardless of how the code behaves. Four defects made that worse; all four are
now fixed and pinned by tests (see `docs/OPERATIONS_GUIDE.md` §5):

| Defect | Effect | State |
|---|---|---|
| relevance scoring ran over the whole candidate pool | 291 papers scored to keep 30; the day's allowance gone before extraction started | **fixed** — `candidate_window` bounds it to `cap × 3` |
| the quota category was lost between the retry layer and the router | `RLA_FALLBACK_ON_QUOTA=1` could never fire; a configured fallback model was unreachable | **fixed** — `retry.py` raises `ProviderQuotaExhausted` |
| the orchestrator pinned `strong_model` for extraction/resolution | `RLA_STRUCTURED_MODEL` never reached the two largest consumers | **fixed** |
| the capability gate refused self-hosted models | every structured stage unreachable on a local model | **fixed** — `RLA_STRUCTURED_OUTPUT_MODELS` |

The remaining constraint is arithmetic, not code. A local model routed through LiteLLM removes it.

---

## 1. Environment reality check

The spec assumes a Linux box with Docker and several paid API keys. This machine is Windows with
neither. Every deviation below is forced, not preferred.

| Spec | Reality on this machine | Decision |
|---|---|---|
| SerpApi Google Scholar pass (§3a) | no `SERPAPI_API_KEY` | Keyless coverage via Semantic Scholar, OpenAlex, arXiv, DBLP, CrossRef. SerpApi implemented as a **key-gated adapter**, disabled by default. P1 prints a per-source coverage report so the blind spot is visible, not hidden. |
| Neo4j graph store (§3c) | Docker not installed | **NetworkX** primary (§3c already permits this). Persist `graph.json` + `graph.graphml`. A Neo4j import script ships in P9 for when a server is available — **still not written**. |
| GROBID full-text structuring (§3b) | Java 8 only; GROBID needs JDK 17+ | **Abstract-only MVP.** Phase 2 uses PyMuPDF heading-based section splitting. GROBID documented as an optional upgrade, not a dependency. `pyproject` declares a `fulltext` extra; no module uses it yet. |
| Claude via Anthropic (§3d) | only `GEMINI_API_KEY` set | `LLMClient` **protocol** + Gemini implementation, plus an optional LiteLLM backend (P9). Anthropic/OpenAI adapters are drop-ins requiring only a key. |
| Unpaywall (§3a) | needs an email, not a key | Keyless in Phase 2 via `UNPAYWALL_EMAIL`. Setting exists; adapter does not. |
| CORE (§3a) | needs a key | `RLA_CORE_API_KEY` setting exists; adapter does not. |
| Neo4j Bloom visual demo | needs a server | Deferred; D3 static export in P9 — **still not done** (only the D3-shaped `graph.json` exists). |

Confirmed working: Python 3.12.11, `pip` with live PyPI access, Node 24, git, **a valid AI Studio
`GEMINI_API_KEY`** (verified live 2026-10-01 — the earlier blocker was an OAuth token in
`.env`, since replaced). Textual requires **Windows Terminal** (not legacy conhost).

---

## 2. Module layout

As built (names differ from the first draft of this plan in three places: `pipeline/extraction.py`
not `extract.py`, `store/` gained `extraction_store.py`, and `llm/` gained a routing layer).

```
src/rla/
├─ config.py                 pydantic-settings; every key optional except GEMINI_API_KEY
├─ models.py                 Paper, Concept, Relation, Extraction, Corpus (pydantic)
├─ events.py                 Event(phase, kind, message, payload) + PIPELINE_PHASES
├─ errors.py                 package-level error types
├─ llm/
│  ├─ base.py                LLMClient Protocol, structured-output contract, usage recording
│  ├─ router.py              ProviderRouter: model selection, capability gate, fallback
│  ├─ factory.py             build_backend / build_client / build_embedder (provider choice)
│  ├─ gemini.py              native google-genai backend
│  ├─ litellm_backend.py     optional LiteLLM backend (lazy import, `[router]` extra)
│  ├─ embeddings.py          Gemini concept embeddings
│  ├─ embedding_base.py      cosine + dimension-mismatch guard
│  ├─ errors.py              ErrorCategory + ProviderError family (policy per category)
│  ├─ error_map.py           any SDK exception -> a category (shared by retry and router)
│  ├─ usage.py               TokenUsage; unknown is not zero
│  ├─ retry.py               pacing, retry, per-run budget, daily-quota fail-fast
│  └─ prompts/templates.py   versioned prompt modules (hashed into the cache key)
├─ sources/
│  ├─ base.py                Source protocol + cached/rate-limited HTTP fetcher
│  ├─ semantic_scholar.py  openalex.py  arxiv.py  dblp.py  crossref.py
│  ├─ serpapi.py             key-gated supplementary pass
│  └─ dedup.py               DOI + normalized-title matching
├─ pipeline/
│  ├─ query_expansion.py     title -> 3-5 queries (§2 L1)
│  ├─ acquisition.py         multi-source fan-out + snowball (§2 L1)
│  ├─ scoring.py             batched LLM relevance 1-5
│  ├─ extraction.py          concept/limitation extraction, polarity filter (§2 L2)
│  ├─ resolve.py             3-tier entity resolution / merge (§9)
│  ├─ graph_build.py         NetworkX build + relation→edge mapping + temporal constraints
│  ├─ traverse.py            5 traversal strategies (§6)
│  ├─ gaps.py                table → themes → structural → rank → suppress (§7)
│  ├─ answer.py              subgraph -> cited narrative (§2 L4)
│  └─ orchestrator.py        event-emitting async generator (§8)
├─ store/{cache.py, extraction_store.py, graph_store.py}
├─ tui/{app.py, state.py}    Kiro-style terminal UI (§2 L5, §8)
├─ eval/{ground_truth,metrics,baseline_rag,judge,gap_validity,run_eval}.py   (§10)
└─ cli.py                    typer entrypoint (10 commands)
```

---

## 3. Milestones and acceptance gates

A milestone is done only when its gate passes. Gates are automated where possible
(`pytest tests/test_pN_*.py`) so regressions are caught, not remembered.

### P0 — Foundation — **achieved**

Scaffold, config, models, event bus, SQLite cache (HTTP **and** LLM), CLI skeleton.

- **Gate:** `rla --help` runs; `pytest` green; *every* outbound request goes through the cache.
  Rationale: rate-limit resilience must exist before P1, not be retrofitted.
- **Verified:** 529 tests green; `test_a6_a_cache_hit_prevents_any_provider_call` asserts that a
  second identical call touches the provider zero times, for both structured and streamed calls.
- **Beyond the original gate:** the provider layer was refactored behind a factory + router (P9)
  and three latent defects were found and fixed by an audit — a dropped `strong_model` argument,
  an unbounded provider call, and an answer stage that reported $0.00.

### P1 — Acquisition (§2 Layer 1, §4) — **achieved**

Gemini query expansion into 3-5 queries; five keyless sources fanned out concurrently; DOI +
normalized-title dedup; 1-hop snowball via S2 references/citations with OpenAlex fallback; LLM
relevance 1-5 filter down to a bounded corpus.

- **Gate:** `data/corpus.json` holds a bounded paper set, zero duplicate DOIs, ≥90% carry year +
  abstract. Re-running `rla build` performs **zero** network calls. Per-source yield is printed.
- **Verified live** (current `.env`: `RLA_TARGET_CORPUS_MIN=15`, `RLA_TARGET_CORPUS_MAX=30`):
  30 papers, 30 abstracts, 30 years, 29 DOIs, 0 duplicate DOIs; yield Semantic Scholar 25,
  OpenAlex 25, arXiv 20, CrossRef 15; years 1997-2024.
- **Relevance filtering is now proven.** The stored scores are 3×17, 4×10, 5×3 — a real spread,
  and the unscored default is exactly 3. The earlier "all 3" run predates the working key.
- **Cache-only rerun:** `test_a_second_run_reaches_no_network`.
- **Residual blind spots, both named in output rather than hidden:** DBLP still answers with an
  Anubis bot-protection page and contributes nothing; SerpApi is unconfigured, so recent
  preprints are a gap. `rla sources` shows both.
- **Note on the corpus size:** the spec's 40-100 target is now a *config* range, not a constant.
  It is set to 15-30 in `.env` because a 30-paper corpus is what the daily LLM allowance can
  actually extract. Restore `RLA_TARGET_CORPUS_MIN=40` / `MAX=100` with a paid key.

### P2 — Concept extraction (§2 Layer 2) — **partially achieved**

One structured-output LLM call per paper producing: summary, canonical method names, what it builds
on, relation type (`extends|replaces|combines|applies-to-new-domain|critiques`), stated limitation,
inferred open problem. Resumable via content hash.

- **Gate:** 100% valid-JSON parse rate across a 20-paper run; an interrupted run resumes without
  re-calling the LLM; per-stage token/cost report printed.
- **Verified by tests** (`test_p2_extraction.py`): 100% parse rate; a run stopped after two papers
  resumes and calls the model only for the three that were never stored; a changed abstract
  invalidates its stored extraction; per-stage cost report attributes calls, tokens and estimated
  USD; one bad paper does not sink the batch; a corrupt store line is skipped rather than fatal.
- **Verified live:** `data/extractions.jsonl` holds 26 real extractions, 26/26 parsed, with
  substantive summaries and 6 concepts per paper. The gate's parse-rate claim now rests on a real
  run, not a mock.
- **NOT achieved — the limitation field is empty on all 26.** Every stored `stated_limitation` is
  `""`, so `inferred_open_problem` is `""` too (by design). This is the single most consequential
  gap in the project: §7 gap synthesis is downstream of it, and §2 Layer 2's headline requirement —
  the limitation must come from a real Limitations section, not be invented — has no output to show.
  Two candidate causes, not yet separated: (a) abstracts genuinely often contain no self-stated
  limitation, and (b) the polarity filter `is_prior_work_limitation` is over-firing — the sample
  extraction's summary literally reads "It **addresses limitations of** existing DRL methods", which
  that filter is designed to strip.
- **Behaviour worth knowing:** identical failures are reported once (max 3) and then counted; a
  `401`/`403` stops the stage immediately instead of paying for 100 rejected requests; a spent
  allowance stops it too, saving what it has and saying how to resume. A `429` is treated as
  transient and ridden out.

### P3 — Entity resolution (§9) — **partially achieved**

Embed concept `name + description`, cluster by cosine similarity, LLM judge on borderline pairs
only, merge aliases.

- **Gate:** "GAT" and "graph attention networks" resolve to one node; a 10-pair manual sample
  shows no over-merge; every merge decision is logged with its evidence.
- **Three of the four sub-claims hold, and one fails.** Against the live `data/concepts.json`:
  - *Decisions are logged with evidence* — **holds.** 41 decisions, each with `verdict`, `reason`
    (`auto-similarity` or `llm-judge`) and the cosine value. Refusals are logged too, which is what
    makes the over-merge check auditable rather than a vibe.
  - *The LLM judge actually runs* — **holds.** `rla doctor --llm` reaches the models, and the
    stored decisions include `reason: "llm-judge"` at cosines 0.886-0.893, correctly refusing to
    merge `Graph Convolutional Network` with `Graph Neural Networks`.
  - *No over-merge observed* — **holds so far**, on the sample that exists.
  - *"GAT" and "graph attention networks" resolve to one node* — **FAILS.** The live concept set
    contains `Graph Attention Networks`, `Graph Attention Network`, `Graph Attention Networks (GAT)`,
    and `graph attention` as four separate nodes. Root cause is tier 1: `normalise_name` folds
    case and punctuation only, so singular/plural and acronym-vs-long-form are both invisible to
    it, and the judge then rules on them from embeddings alone.
- **Three tiers, cheapest first**, because over-merging is the expensive error — a wrongly fused
  node silently deletes a lineage path, whereas a missed merge only leaves a visible duplicate:
  1. *Normalised name* — case/punctuation folding, no model. Deliberately does **not** expand
     acronyms or plurals, since "GAT" → "graph attention networks" is a judgement, not a string
     operation. This tier alone makes the stage work with no API key.
  2. *Auto-merge* — cosine ≥ `AUTO_MERGE` (0.92) on the `name: description` centroid. No call spent.
  3. *LLM judge* — cosine in `[MAYBE_MERGE, AUTO_MERGE)` only. A judge failure or refusal **never**
     merges; the stage fails toward duplicates, not toward false lineage.
- **Cost bound:** judging is the only per-pair spend, capped at `MAX_JUDGE_CALLS` (40),
  most-similar pairs first, and the cutoff is reported as a warning. The free tiers are never
  rationed.
- **Canonical naming:** the judge's `canonical` outranks the frequency heuristic, which outranks
  name length. Remaining spellings are kept as `aliases`, never discarded.
- **Degradation:** no key, or an embedding failure, falls back to tier 1 with an explicit warning.
  An embedding dimension mismatch now **raises** rather than silently scoring every pair 0.0 — that
  silent failure had stopped resolution from merging while reporting nothing.
- **To close the gate:** widen tier 1 (singular/plural folding at minimum) or widen the judge band,
  then re-run resolution on a fresh corpus and re-take the 10-pair sample by hand.

### P4 — Graph construction (§2 Layer 3, §5) — **achieved**

NetworkX directed graph with the §5 node/edge schema. `CITES` edges come from citation ground truth
(no LLM). **Temporal constraint:** any `EXTENDS`/`REPLACES` edge whose child year ≤ parent year is
dropped as impossible.

- **Gate:** schema test asserts zero temporal violations; graph round-trips through `.json` and
  `.graphml` without loss. Both hold, and both are checked rather than assumed: the stage re-runs
  `enforce_temporal_constraints` after building and raises an `error` event if any violation
  survives, and the round-trip test asserts node set, edge set *with keys*, and per-edge `evidence`.
- **Verified live:** 135 nodes (30 papers, 105 concepts), 104 edges (64 `CITES`, 35 `EXTENDS`,
  5 `COMBINES_WITH`), `graph.graphml` written.
- **Edge direction:** `A --EXTENDS--> B` means "B builds on A", so the arrow runs parent → child and
  the child must be strictly newer. Getting this backwards would delete every legitimate lineage
  edge while keeping the impossible ones.
- **Lineage is anchored only on concepts a paper `introduces`.** A paper that merely *uses* a
  concept created no new version of it, so it forms no concept-to-concept edge. This is also what
  keeps backwards edges from reaching the temporal filter in the first place.
- **Relation mapping.** The extraction prompt returns five relation verbs but §5 defines seven edge
  types, and they do not line up. `extends`/`replaces`/`combines` become concept-to-concept lineage;
  `critiques` becomes `Paper --HAS_LIMITATION--> Concept`; `applies-to-new-domain` becomes
  `Paper --USES--> Concept`. `builds_on` is the primary lineage signal and produces one `EXTENDS`
  edge per introduced concept.
- **Unresolvable names are reported, not dropped.** Extraction targets are free text, matched back
  by canonical name, alias, and P3 normalised form. Anything unmatched is listed in
  `unresolved_targets` with the paper and the field it came from.
- **Every derived edge records its paper** in `evidence` (`p12: builds_on attention`), so any edge
  can be traced back to the extraction that produced it.
- **Known data hazard (not a code defect, but it needs a guard).** `store/graph_store.py:add_relations`
  *silently skips* any relation whose endpoint is not in the graph. A `data/extractions.jsonl` left
  over from a different corpus therefore produces a graph with **zero** `INTRODUCES`/`USES`/
  `HAS_LIMITATION` edges and no error — which is exactly the current state of this working tree,
  because the committed 30-paper corpus and the committed 26-extraction store share **zero** paper
  ids. The graph report does record `papers_without_extraction`, so the signal exists; nothing
  surfaces it. See the recovery recipe in `docs/OPERATIONS_GUIDE.md`.

### P5 — Traversal + answer generation (§2 Layer 4, §6) — **achieved**

Five pure functions `graph, question -> subgraph`, one per question type in §6. Narrative generation
streams from the subgraph with `[P12]`-style inline citations.

- **Gate:** unit tests over a hand-built fixture assert the exact expected subgraph per question
  type. A post-generation validator **strips any citation ID not present in the subgraph**.
- **Verified by tests** (`test_p5_traversal.py`, `test_p5_answer.py`): all five strategies
  (lineage, gap, comparison, approaches, full-report) over a fixed fixture; question
  classification is keyword-based and deterministic, so it costs nothing and cannot drift.
- **Verified live:** `rla ask "how did graph attention networks evolve?"` classified LINEAGE,
  selected a subgraph, and streamed a cited narrative naming `[C5]`, `[C11]`, `[C14]` and others.
  It also correctly self-reported its own limit — "the subgraph does not provide chronological
  information … for the nodes or edges" — which is the honest answer when concept years are null.
- **Citation guard:** the prompt forbids inventing ids, but a prompt is a request, not a guarantee,
  so ids are validated per chunk against the subgraph and stripped ones are reported.

### P6 — Gap analysis (§7) — **implemented, produces nothing on current data**

Per-paper limitation table → cluster stated gaps by theme → structural gaps (old concept, zero
in-degree `EXTENDS`) → rank by recency/frequency → suppress gaps already closed by a later
in-corpus paper.

- **Gate:** `rla report` emits both the per-paper table and the synthesized cross-paper section,
  every claim carrying at least one citation.
- **Verified by tests** (`test_p6_gaps.py`, `test_p6_report_cli.py`): all five stages over synthetic
  extractions, including suppression by a later in-corpus paper and the refusal to treat a stated
  gap as a structural one.
- **NOT achieved on live data.** `rla report` currently prints: *"26 paper(s) analysed; 0 state a
  limitation"*, and 0 themes, 0 structural gaps, 0 ranked gaps. Both signal sources are empty for
  the same upstream reason: no stated limitations (P2), and every concept's `first_seen_year` is
  `null`, so nothing can be old enough to be "abandoned". The code is not at fault; the input is.
- **Two signals kept deliberately apart:** a stated gap is a limitation a paper admits out loud; a
  structural gap is a silence in the graph. Merging them would make an inference look like a
  quotation.

### P7 — Orchestrator + TUI (§2 Layer 5, §8) — **achieved (automated gate)**

Pipeline is an event-yielding async generator, exactly the `yield Event(...)` shape in §8.
Headless `rla run --jsonl` first. Then a Textual app: status bar with phase + progress, colour-coded
live event log, live traversal tree via `rich.tree.Tree`, streamed answer panel.

- **Gate:** `rla tui` shows all phases live with running graph counters and no UI freeze (async
  worker off the UI thread).
  - Automated: 80×24 composed-frame tests assert all ten phase slots are on screen and uncut, the
    counters bar is bounded, the log wraps rather than truncates, and a slow stage leaves input
    processing live mid-run.
  - **Outstanding:** the literal Windows Terminal visual check is not automated. Run
    `rla tui -t "<topic>"` there and confirm the layout before calling the gate fully met.
- **One invariant makes the headless and TUI paths incapable of drifting:** both subscribe to the
  same `Pipeline.run()` generator. `cli._build_pipeline()` exists solely so `run` and `tui` cannot
  construct the pipeline differently.

### P8 — Evaluation (§10) — **harness implemented, nothing measured**

Hand-labelled 20-paper ground-truth graph → node/edge precision/recall/F1. Plain
RAG-over-abstracts baseline. 10-15 lineage/gap questions scored by LLM-as-judge rubric. Gap validity
checked against held-out later papers.

- **Gate:** `rla eval` prints a comparison table and writes `eval/report.md`. The graph-vs-baseline
  delta is reported honestly even if unfavourable.
- **The letter of the gate is met; the substance is not.** Current `data/eval/report.md`:
  - node/edge precision & recall — **NOT MEASURED** (reference set is 0% hand-labelled, and
    `ground_truth.assess_reference_set` refuses to score against it);
  - graph vs RAG — **not comparable** on all three dimensions, because neither arm has an answer to
    compare;
  - gap validity — **no gaps available to check**;
  - no LLM judge ran.
- **Not achieved, against §10's four experiments:** (1) graph accuracy, (2) answer quality vs
  baseline, (3) gap validity, (4) full-text vs abstract-only. None of the four is measured. Three of
  them are blocked on data (no hand labels, no gaps) and one on Phase 2 not existing.
- **What *was* built** is the part §10 cannot be satisfied without: an eval harness that refuses to
  print a number it cannot measure, states the judge kind next to every score, prints the
  denominator next to every mean, gives unfavourable results equal prominence, and treats a `NOT
  MEASURED` row as a reportable result rather than an error. That property is tested.
- **To actually close this gate:** hand-label ~20 papers into `data/eval/` (the loader is already
  written), re-run extraction so gaps exist, then run `rla eval` with a judge-capable key.

### P9 — Provider routing (LLM layer hardening) — **achieved**

This P9 is **in addition to** the original P9 polish items; it exists because the original P0
`LLMClient` abstraction was never actually load-bearing.

- **Gate (A1-A8, `test_p9_acceptance.py`):** no module outside `llm/` imports a provider SDK;
  LiteLLM is imported lazily; the CLI and orchestrator build through the factory, never naming a
  concrete client; selecting a provider is configuration only; all four production schemas are
  valid JSON Schema; a cache hit prevents any provider call; every default model has a price.
- **Verified:** all of A1-A8 pass. Gemini is validated live; OpenAI and Anthropic are configured
  paths that have **not** been exercised (`docs/llm_provider_validation.md`).
- **Three real defects the audit found and closed:** a `strong_model` argument that was accepted by
  two stages and used only to label a cost report (the configured model never reached the
  provider); provider calls with **no timeout** at all (`request_timeout_seconds` only ever
  applied to source HTTP); and a `stream_text` that never recorded usage, so the only consumer of the
  strong model reported $0.00.
- **Retry stays in one place:** LiteLLM is called with `num_retries=0` and RLA's `call_with_retry`
  does the retrying, so a call can never pass through two retry loops.

### P9 (original) — Polish and write-up — **partially achieved**

| Item | State |
|---|---|
| README | done, and current |
| Architecture diagram | as text/ASCII only; no drawn diagram |
| 3-minute demo script | done — `docs/demo_commands.md` §12 |
| Measured cost/runtime | partial — a cost tracker and per-stage report exist; a published run-level number does not |
| Limitations section | done — README "Known limitations" |
| Neo4j import script | **not written.** Settings (`RLA_NEO4J_*`) exist with no consumer |
| Optional D3 static export | **not written.** `graph.json` is D3-shaped by coincidence, not by design |

### P10 — Per-provider base URLs — **achieved**

`RLA_LLM_BASE_URLS` is a JSON object keyed by the same provider prefix used in model strings.

- **Why a map and not one URL:** during cross-provider failover two providers are live at once, and
  a shared endpoint would silently break the primary.
- **Behaviour:** a bare model id is treated as the primary provider, so a `gemini` key applies to
  the project's default model strings; malformed JSON is ignored with one warning rather than
  stopping the pipeline; an absent key means "use the provider's default endpoint".
- **Honest limit:** the prefix must be one LiteLLM actually recognises (`openai`, `openrouter`,
  `groq`, `gemini`, `anthropic`). An invented name like `local` is rejected by LiteLLM *before* any
  request goes out. To reach a custom OpenAI-compatible server, declare it *as* `openai` and
  override the endpoint.
- Applies to the **LiteLLM path only**; the native Gemini backend talks directly to Google.

### P11 — Readable failures in the answer stage — **achieved**

`rla ask` is the one command a human reads at a terminal, so a multi-kilobyte provider JSON blob
printed there is worst. `_reason` now emits `category: guidance. <truncated provider text>`, with
guidance first and the blob last so the instruction is what survives truncation.

- **Verified** (`test_p11_answer_errors.py`): the blob is cut to 200 characters *and* the actionable
  sentence survives the cut — including the one that matters most, "this is a daily cap, not a
  burst; set `RLA_FALLBACK_ON_QUOTA=1`".

### P12 — Multi-provider routing and local inference — **achieved**

`ProviderRouter` stays the sole owner of precedence, capability policy, and fallback
eligibility and ordering; `MultiBackend` (`src/rla/llm/multi.py`) implements the existing
`RoutingBackend` protocol and resolves each model id to its owning backend, so
cross-provider fallback needs no router change (ADR-0006). A native Ollama backend
(`/api/generate` with `format: <schema>`, lazily constructed) and an Ollama embedding
provider sit alongside Gemini and LiteLLM; merge thresholds are keyed per canonical
embedding-model id, with uncalibrated spaces failing toward duplicates (ADR-0007).
`rla calibrate-merges` proposes a threshold from the measured similarity distribution
and installs nothing — a human commits it.

- **Achieved:** four-rung precedence with a transient session override above the
  explicit `model=` argument (`test_p12_tui_wiring.py`, `test_p12_cli_and_doctor.py`);
  `MultiBackend` dispatch and lazy construction (`test_p12_multi_backend.py`,
  `test_p12_providers.py`); native Ollama structured output and capability honesty
  (`test_p12_ollama_backend.py`); Ollama embeddings with canonical cache keys
  (`test_p12_embeddings.py`); per-space thresholds and propose-without-install
  calibration (`test_p12_calibration.py`); a fully local run with no Gemini key.
- **Benchmark, not a gate** (measured 2026-10-02, same model/paper/schema/temperature):
  **8.1 s** native vs **97.6 s** via LiteLLM. The native route removes
  compatibility/prefill overhead (~4096 vs ~662 prompt tokens), not intrinsic
  token-generation speed. Latency depends on model load and machine state, so this
  is recorded, not asserted.
- **Partially achieved:** the TUI routing surface is split — the router-side pieces
  (session overrides, `on_fallback`, precedence) are done; panel, widgets and status
  rows belong to the TUI workstream.
- **Not achieved:** `OllamaBackend.stream_text` still uses synchronous HTTP and must
  become non-blocking before the TUI answer-stream path ships; no second remote
  provider has been exercised live.

### Phase 2 (explicitly outside the MVP) — **not started**

Full-text pipeline (PyMuPDF → optional GROBID), Unpaywall/CORE resolution, and evaluation
experiment #4 (full-text vs abstract-only extraction quality) which justifies that added complexity.

- `FULLTEXT` exists as a phase slot so the status bar and the event stream show the real order, and
  it emits a `pending` event. There is no implementation behind it.

---

## 4. Cross-cutting rules (built in P0, not retrofitted)

- **Prompt versioning** — each prompt module is hashed into the LLM cache key, so editing a prompt
  invalidates exactly the affected calls and nothing else.
- **Determinism** — temperature 0 for extraction; the corpus snapshot is committed so evaluation
  numbers are reproducible across runs.
- **Rate limits** — Semantic Scholar anonymous access is roughly 1 req/s (`s2_delay_seconds`).
  Concurrency semaphore, exponential backoff, and per-stage resume all exist from P1.
- **Hallucination guards** — temporal ordering (P4), citation-ID validation (P5), and relation
  precision measured on a manual sample (**never performed**; §9 of the spec asks for 30-50 edges
  and the P8 gate depends on it).
- **Cost visibility** — token counts and estimated cost accumulated per stage, printed at the end of
  every run. Unknown usage is reported as unknown, not as $0.00.
- **Error taxonomy as policy** — every provider error is normalised to one of ten `ErrorCategory`
  values, and retry-ability and fallback-ability are *derived* from the category, so no call site
  re-decides them. See `docs/OPERATIONS_GUIDE.md` §"Model routing".

---

## 5. Risk register

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| Semantic Scholar / OpenAlex 429s stall a build | High | SQLite cache + throttle + per-stage resume, live from P0/P1 | closed |
| Concept over-merge corrupts lineage answers | High | LLM judge on borderline pairs only; manual 10-pair gate in P3 | **open** — gate not taken |
| Concept *under*-merge fragments lineage | High | tier-1 normalisation + judge + logged refusals | **realised** — see P3 |
| LLM hallucinates `EXTENDS` edges | High | Temporal constraint (P4) + citation-grounded prompt + measured precision | partly closed; **precision never measured** |
| No stated limitations → no gaps | High | full text (Phase 2); polarity-filter review | **realised** — see P2 |
| Stale `extractions.jsonl` silently empties paper→concept edges | High | `papers_without_extraction` is reported; no guard raises | **realised** — see P4 |
| Gemini quota or cost overrun | Medium | flash-class structured model, strong only for synthesis; per-run budget; per-model fallback chain | mitigated, not solved on the free tier |
| No SerpApi → recent preprints missed | Medium | arXiv/DBLP/CrossRef coverage; P1 coverage report names the blind spot explicitly | open, accepted |
| DBLP behind bot protection | Low | it contributes 0 papers and says so in `rla sources` | accepted |
| Entity-resolution embeddings need a local model | Low | Gemini `text-embedding` via the existing key; no torch install | closed |
| Textual misbehaves on legacy conhost | Low | Documented requirement: Windows Terminal | closed |
| Concept drift makes evaluation meaningless | Medium | Frozen, committed corpus snapshot for all eval runs | closed |

---

## 6. Commands

Ten commands. `--jsonl` gives machine-readable output on `run`, `build`, `ask`, and `report`.

| Command | Reads | Needs a key? |
|---|---|---|
| `rla doctor [--llm]` | config, sources, cache; `--llm` probes every model live, uncached | `--llm` only |
| `rla sources [--probe Q] [--cache]` | probes every source against a throwaway cache DB | no |
| `rla stats` | stored corpus + built graph summary | no |
| `rla events` | the 10 pipeline phases, in order | no |
| `rla build -t "…"` | acquisition only (P1) | no — keyless sources |
| `rla run -t "…" [-q "…"]` | full pipeline, streams `Event`s | optional (degrades) |
| `rla ask "…"` | `data/graph/graph.json` only; no re-acquisition | for the narrative |
| `rla report` | corpus + extractions + graph | no — every claim traces to a stored extraction |
| `rla eval` | writes `data/eval/report.md` + `results.json` | no |
| `rla tui -t "…"` | the same event stream as `rla run`; needs `textual`, **Windows Terminal** | optional |

`rla ask` and `rla eval` need `data/graph/graph.json`, which only exists after a run that built a
graph; that path is gitignored, so a fresh clone must run `rla run` / `rla build` first.

---

## 7. Effort: estimate vs actual

Solo. The estimate below was written before P9-P11 existed.

| Phase | Est. days | Actual |
|---|---|---|
| P0 Foundation | 1 | 1 |
| P1 Acquisition | 2 | 2 |
| P2 Extraction | 2 | 2 + data problem still open |
| P3 Entity resolution | 1.5 | 2 — tier-1 normalisation is the part that needs work |
| P4 Graph build | 1 | 1.5 — the stale-store hazard was found late |
| P5 Traversal + answers | 2 | 2 |
| P6 Gap analysis | 1.5 | 1 |
| P7 Orchestrator + TUI | 2 | 2 |
| P8 Evaluation | 2 | 3 — most of it harness, because the measurements are blocked on data |
| P9 Provider routing | — | 4 (not in the original plan; found by audit, not by design) |
| P10 Base URLs | — | 0.5 |
| P11 Answer errors | — | 0.5 |
| P9 Polish (original) | 1 | 1, minus the two unwritten deliverables |
| **Phase 2 (full text)** | **+3** | **0 — not started** |

---

## 8. Demo topics

The original demo topic was **"Graph-based agent architectures"** — it sits inside this project's own
domain and yields live citations (MAGMA, G-Designer, Graph-of-Agents). The corpus that actually
produced the committed artefacts is **"Graph Neural Network"**, run at a 30-paper cap because that
is what the daily LLM allowance can extract.

For a demo, prefer `"Graph Attention Networks"`: it produces a lineage chain that answers
cleanly, which is the half of the product that currently works.

---

## 9. Verification log

How to reproduce each claim above. All of these run against the venv.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q      # 529 passed in ~68s
.\.venv\Scripts\python.exe -m ruff check src/ tests/
rla doctor                                          # config, sources, cache
rla doctor --llm                                    # live: all three models reachable
rla stats                                           # corpus + graph counts
rla ask "how did graph attention networks evolve?"  # live cited answer
rla report                                          # limitations + gaps (currently empty)
rla eval                                            # NOT MEASURED, honestly
```

Live LLM numbers are day-dependent: the Gemini free tier allows ~20 requests per model per day, and
the pipeline's own budget is 200 (`RLA_LLM_DAILY_BUDGET`). A rerun may therefore produce different
extraction counts from the ones recorded here. Cached calls are free and always reproduce.

---

## 10. Spec coverage

What §12 "Recommended First-Version Scope" and §11 "Build Order" asked for, against what exists.

| Spec | State |
|---|---|
| §2 L1 acquisition, multi-source, dedup, snowball, relevance filter | achieved |
| §2 L2 extraction incl. **stated limitation from the Limitations section** | implemented; **empty output** — abstract-only cannot reach a section that is not in the abstract |
| §2 L3 graph construction | achieved |
| §2 L4 traversal + cited narrative | achieved |
| §2 L5 TUI | achieved |
| §3a S2 / OpenAlex / arXiv / CrossRef / DBLP | achieved (DBLP yields 0) |
| §3a SerpApi | implemented, unconfigured |
| §3a CORE / Unpaywall | settings only |
| §3b GROBID | replaced by PyMuPDF in Phase 2; not started |
| §3c NetworkX / Neo4j | NetworkX achieved; Neo4j import **not written** |
| §3d LLM protocol / embeddings | achieved, and generalised beyond the spec (P9) |
| §3e LangGraph | not used; custom orchestrator, which §3e explicitly permits |
| §3f Textual + Rich | achieved |
| §3g D3 | not written |
| §4 acquisition flow steps 1-3, 6, 7 | achieved |
| §4 steps 4-5 (Unpaywall/CORE → GROBID) | Phase 2 |
| §5 seven edge types, two node types | all defined; a live graph currently carries 3 of 7 |
| §6 five traversal strategies | achieved |
| §7 five-stage gap synthesis | implemented; no live output |
| §8 event-driven pipeline + TUI panels | achieved |
| §9 entity resolution | partial (under-merging, see P3) |
| §9 multi-source dedup | achieved |
| §9 relationship-extraction precision | **never measured** |
| §9 temporal correctness | achieved |
| §9 scale-vs-quality measurement | **never measured** |
| §10 eval experiments 1-4 | none measured; harness refuses to fake them |
| §12 one narrow topic, 40-100 papers | achieved in shape; the cap is now config (15-30 in `.env`) |
| §12 MVP = S2 first, others as enhancement | exceeded — all five keyless sources run every time |

---

## 11. Where to go next, in priority order

1. **Route the high-volume stages to a local model.** The only durable answer to a 20-request/day
   ceiling. The code supports it now; it needs the model pulled
   (`ollama pull <model>`) and the `.env` block from `docs/OPERATIONS_GUIDE.md` §5.
2. **Fix the limitation field (P2).** Decide whether abstracts simply do not carry stated
   limitations or whether `is_prior_work_limitation` is over-firing, then fix it. Nothing in §7 is
   demonstrable until this produces rows.
3. **Widen tier-1 normalisation (P3).** Singular/plural folding is a two-line change and would
   collapse `Graph Attention Network` / `Graph Attention Networks` / `Graph Attention Networks
   (GAT)` without spending a call. Then re-take the gate's 10-pair sample by hand.
4. **Guard the stale extraction store (P4).** Raise a `warn` event when
   `len(papers_without_extraction) == len(papers)`; today the graph silently loses every
   paper→concept edge.
5. **Hand-label ~20 papers (P8).** The eval harness is finished and waiting; the reference set is
   the only thing between it and real numbers.
6. **Measure relation precision on 30-50 edges.** §9 and §4 both promise it; it is a day's manual
   work and it is the honest defence of the `EXTENDS` edges.
7. **Then, and only then, Phase 2 full text** — because experiment #4 is what justifies its cost.