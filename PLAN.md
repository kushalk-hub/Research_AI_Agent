# PLAN — Research Literature Assistant Agent

An intelligent agent that takes a **research project title**, ingests relevant papers, builds a
**citation-and-concept graph**, and traverses that graph to answer *lineage* questions
("how did technique X evolve?") and *gap* questions ("what's still unsolved in Y?") with traceable
citations.

Derived from [`research-literature-agent-project-final.md`](research-literature-agent-project-final.md).
Section numbers below in the form (§N) refer to that spec.

---

## 1. Environment reality check

The spec assumes a Linux box with Docker and several paid API keys. This machine is Windows with
neither. Every deviation below is forced, not preferred.

| Spec | Reality on this machine | Decision |
|---|---|---|
| SerpApi Google Scholar pass (§3a) | no `SERPAPI_API_KEY` | Keyless coverage via Semantic Scholar, OpenAlex, arXiv, DBLP, CrossRef. SerpApi implemented as a **key-gated adapter**, disabled by default. P1 prints a per-source coverage report so the blind spot is visible, not hidden. |
| Neo4j graph store (§3c) | Docker not installed | **NetworkX** primary (§3c already permits this). Persist `graph.json` + `graph.graphml`. A Neo4j import script ships in P9 for when a server is available. |
| GROBID full-text structuring (§3b) | Java 8 only; GROBID needs JDK 17+ | **Abstract-only MVP.** Phase 2 uses PyMuPDF heading-based section splitting. GROBID documented as an optional upgrade, not a dependency. |
| Claude via Anthropic (§3d) | only `GEMINI_API_KEY` set | `LLMClient` **protocol** + Gemini implementation. Anthropic/OpenAI adapters are drop-ins requiring only a new class + a key. |
| Unpaywall (§3a) | needs an email, not a key | Keyless in Phase 2 via `UNPAYWALL_EMAIL`. |
| Neo4j Bloom visual demo | needs a server | Deferred; D3 static export in P9. |

Confirmed working: Python 3.12.11, `pip` with live PyPI access, Node 24, git. Textual requires
**Windows Terminal** (not legacy conhost).

---

## 2. Module layout

```
FODS_CP/
├─ PLAN.md                      this file
├─ README.md                    quickstart
├─ research-literature-agent-project-final.md   original spec (read-only)
├─ pyproject.toml
├─ .env.example
├─ .gitignore
├─ data/
│  ├─ raw/                      raw API JSON per paper (debuggable, gitignored)
│  ├─ cache.db                  SQLite HTTP + LLM cache
│  ├─ corpus.json               deduped working corpus (committed: eval reproducibility)
│  └─ graph/graph.json|graphml  built graph
├─ src/rla/
│  ├─ config.py                 pydantic-settings; every key optional except GEMINI_API_KEY
│  ├─ models.py                 Paper, Concept, Relation, Extraction, Corpus (pydantic)
│  ├─ events.py                 Event(phase, kind, message, payload) + async event bus
│  ├─ llm/
│  │  ├─ base.py                LLMClient protocol, structured-output contract
│  │  ├─ gemini.py              google-genai implementation
│  │  ├─ embeddings.py          concept entity-resolution embeddings
│  │  └─ prompts/               versioned .py prompt modules
│  ├─ sources/
│  │  ├─ base.py                Source protocol
│  │  ├─ semantic_scholar.py  openalex.py  arxiv.py  dblp.py  crossref.py
│  │  ├─ serpapi.py             key-gated supplementary pass
│  │  └─ dedup.py               DOI + normalized-title matching
│  ├─ pipeline/
│  │  ├─ query_expansion.py     title -> 3-5 queries (§2 L1)
│  │  ├─ acquisition.py         multi-source fan-out + snowball (§2 L1)
│  │  ├─ scoring.py             LLM relevance 1-5
│  │  ├─ extract.py             concept/limitation extraction (§2 L2)
│  │  ├─ resolve.py             entity resolution / merge (§9)
│  │  ├─ build_graph.py         NetworkX build + temporal constraints (§2 L3)
│  │  ├─ traverse.py            5 traversal strategies (§6)
│  │  ├─ gaps.py                cluster + structural gaps + ranking (§7)
│  │  ├─ answer.py              subgraph -> cited narrative (§2 L4)
│  │  └─ orchestrator.py        event-emitting async generator (§8)
│  ├─ store/{cache.py,graph_store.py}
│  ├─ tui/{app.py,widgets/,theme.tcss}       Kiro-style terminal UI (§2 L5, §8)
│  ├─ eval/{ground_truth,metrics,baseline_rag,judge,run_eval}.py   (§10)
│  └─ cli.py                    typer entrypoint
└─ tests/
```

---

## 3. Milestones and acceptance gates

A milestone is done only when its gate passes. Gates are automated where possible
(`pytest tests/test_gate_pN.py`) so regressions are caught, not remembered.

### P0 — Foundation
Scaffold, config, models, event bus, SQLite cache (HTTP **and** LLM), CLI skeleton.

- **Gate:** `rla --help` runs; `pytest` green; *every* outbound request goes through the cache.
  Rationale: rate-limit resilience must exist before P1, not be retrofitted.

### P1 — Acquisition  (§2 Layer 1, §4) — **done**
Gemini query expansion into 3-5 queries; five keyless sources fanned out concurrently; DOI +
normalized-title dedup; 1-hop snowball via S2 references/citations, falling back to OpenAlex
`cites`/`cited_by` when S2 is throttled; LLM relevance 1-5 filter down to 40-100 papers.

- **Gate:** `data/corpus.json` holds 40-100 papers, zero duplicate DOIs, >=90% carry year + abstract.
  Re-running `rla build` performs **zero** network calls. Per-source yield is printed.
- **Gate result:** 100 papers, 100 with abstracts, 100 with years, 93 with DOIs, 0 duplicate DOIs;
  196 candidates deduplicated with 403 citation edges resolved; cache-only rerun asserted in
  `test_a_second_run_reaches_no_network`. Snowball contributes 113 of the 196 candidates.
- **Deviation:** relevance scoring did not actually run in the live run - the configured
  `GEMINI_API_KEY` is an OAuth token, so every scoring call was rejected and all papers held the
  default score of 3. Query expansion likewise fell back to the raw title, so only one query was
  issued instead of 3-5. The gate still passes because acquisition is keyless and the corpus is
  built, but relevance filtering is unproven until a real AI Studio key is supplied.
- **Known limits:** DBLP answers with an Anubis bot-protection page, so it contributes nothing
  (`rla sources` shows this); SerpApi is unconfigured, leaving recent preprints as a blind spot.

### P2 — Concept extraction  (§2 Layer 2) — **implemented, gate unverified**
One structured-output LLM call per paper producing: summary, canonical method names, what it builds
on, relation type (`extends|replaces|combines|applies-to-new-domain|critiques`), stated limitation,
inferred open problem. Resumable via content hash.

- **Gate:** 100% valid-JSON parse rate across a 20-paper run; an interrupted run resumes without
  re-calling the LLM; per-stage token/cost report printed.
- **Verified by tests** (`test_p2_extraction.py`): 100% parse rate across a 5-paper run; a run
  stopped after two papers resumes and calls the model only for the three that were never stored;
  a changed abstract invalidates its stored extraction; per-stage cost report attributes calls,
  tokens and estimated USD; one bad paper does not sink the batch; a corrupt store line is skipped
  rather than fatal.
- **Not yet verified live.** Every live call returns `401 UNAUTHENTICATED`, so the real parse rate
  and real token spend are unknown until a valid `GEMINI_API_KEY` is configured.
- **Behaviour worth knowing:** identical failures are reported once and then counted rather than
  repeated per paper, and an authentication failure stops the stage immediately instead of paying
  for 100 rejected requests. A `429` is treated as transient and the stage rides it out.

### P3 — Entity resolution  (§9)  — **implemented, live gate pending key**
Embed concept `name + description`, cluster by cosine similarity, LLM judge on borderline pairs only,
merge aliases.

- **Gate:** "GAT" and "graph attention networks" resolve to one node; a 10-pair manual sample shows no
  over-merge; every merge decision is logged with its evidence.
- **Three tiers, cheapest first**, because over-merging is the expensive error — a wrongly fused node
  silently deletes a lineage path, whereas a missed merge only leaves a visible duplicate:
  1. *Normalised name* — case/punctuation folding, no model. Deliberately does **not** expand acronyms,
     since "GAT" → "graph attention networks" is a judgement, not a string operation. This tier alone
     makes the stage work with no API key.
  2. *Auto-merge* — cosine ≥ `AUTO_MERGE` (0.92) on the `name: description` centroid. No call spent.
  3. *LLM judge* — cosine in `[MAYBE_MERGE, AUTO_MERGE)` only, via `CONCEPT_RESOLUTION`. A judge
     failure or refusal **never** merges; the stage fails toward duplicates, not toward false lineage.
- **Cost bound:** judging is the only per-pair spend, capped at `MAX_JUDGE_CALLS` (40), most-similar
  pairs first, and the cutoff is reported as a warning. The free tiers are never rationed.
- **Canonical naming:** the judge's `canonical` outranks the frequency heuristic, which outranks name
  length. Remaining spellings are kept as `aliases`, never discarded.
- **Auditability:** every merge *and* every refusal is written to `data/concepts.json` under
  `decisions` with `reason` and `evidence` (cosine value, threshold, or error text).
- **Degradation:** no key, or an embedding failure, falls back to tier 1 with an explicit warning
  rather than failing the pipeline. That fallback is *why* the GAT gate is still unverified live: a
  keyless run correctly keeps "GAT" and "graph attention networks" apart, because only tiers 2 and 3
  can tell that an acronym is its own long form.
- **Not yet verified live.** Tiers 2 and 3 need a valid `GEMINI_API_KEY`; the 10-pair manual sample
  must be taken on a real run before this gate can be called passed.

### P4 — Graph construction  (§2 Layer 3, §5)  — **done**
NetworkX directed graph with the §5 node/edge schema. `CITES` edges come from citation ground truth
(no LLM). **Temporal constraint:** any `EXTENDS`/`REPLACES` edge whose child year <= parent year is
dropped as impossible.

- **Gate:** schema test asserts zero temporal violations; graph round-trips through `.json` and
  `.graphml` without loss. Both hold, and both are checked rather than assumed: the stage re-runs
  `enforce_temporal_constraints` after building and raises an `error` event if any violation
  survives, and the round-trip test asserts node set, edge set *with keys*, and per-edge `evidence`.
- **Edge direction:** `A --EXTENDS--> B` means "B builds on A", so the arrow runs parent -> child and
  the child must be strictly newer. Getting this backwards would delete every legitimate lineage
  edge while keeping the impossible ones.
- **Lineage is anchored only on concepts a paper `introduces`.** A paper that merely *uses* a
  concept created no new version of it, so it forms no concept-to-concept edge. This is also what
  keeps backwards edges from reaching the temporal filter in the first place.
- **Relation mapping.** The extraction prompt returns five relation verbs but §5 defines seven edge
  types, and they do not line up. `extends`/`replaces`/`combines` become concept-to-concept lineage;
  `critiques` becomes `Paper --HAS_LIMITATION--> Concept`, which is what powers gap detection in P6;
  `applies-to-new-domain` becomes `Paper --USES--> Concept`. `builds_on` is the primary lineage
  signal and produces one `EXTENDS` edge per introduced concept.
- **Unresolvable names are reported, not dropped.** Extraction targets are free text, matched back
  onto resolved nodes by canonical name, alias, and P3 normalised form. Anything that does not match
  is listed in `unresolved_targets` with the paper and the field it came from.
- **Every derived edge records its paper** in `evidence` (`p12: builds_on attention`), so any edge
  can be traced back to the extraction that produced it.

### P5 — Traversal + answer generation  (§2 Layer 4, §6)
Five pure functions `graph, question -> subgraph`, one per question type in §6. Narrative generation
streams from the subgraph with `[P12]`-style inline citations.

- **Gate:** unit tests over a hand-built 12-node fixture assert the exact expected subgraph per
  question type. A post-generation validator **strips any citation ID not present in the subgraph**.

### P6 — Gap analysis  (§7)  - **done**
Per-paper limitation table -> cluster stated gaps by theme -> structural gaps (old concept, near-zero
in-degree `EXTENDS`) -> rank by recency/frequency -> suppress gaps already closed by a later in-corpus
paper.

- **Gate:** `rla report` emits both the per-paper table and the synthesized cross-paper section, every
  claim carrying at least one citation.

### P7 — Orchestrator + TUI  (§2 Layer 5, §8)  — **done**
Pipeline becomes an event-yielding async generator, exactly the `yield Event(...)` shape in §8.
Headless `rla run --jsonl` first. Then a Textual app: status bar with phase + progress, colour-coded
live event log, live traversal tree via `rich.tree.Tree`, streamed answer panel.

- **Gate:** `rla tui` shows all phases live with running graph counters and no UI freeze (async worker
  off the UI thread). Verified in Windows Terminal.
  - Automated: 80×24 composed-frame tests assert all ten phase slots are on screen and uncut, the
    counters bar is bounded, the log wraps rather than truncates, and a slow stage leaves input
    processing live mid-run.
  - **Outstanding:** the literal Windows Terminal visual check is not automated. Run
    `rla tui -t "<topic>"` there and confirm the layout before calling the gate fully met.

### P8 — Evaluation  (§10)
Hand-labelled 20-paper ground-truth graph -> node/edge precision/recall/F1. Plain RAG-over-abstracts
baseline. 10-15 lineage/gap questions scored by LLM-as-judge rubric (correctness, completeness,
citation accuracy). Gap validity checked against held-out later papers.

- **Gate:** `rla eval` prints a comparison table and writes `eval/report.md`. The graph-vs-baseline
  delta is reported honestly even if unfavourable.

### P9 — Polish and write-up
README, architecture diagram, 3-minute demo script, measured cost/runtime, limitations section,
Neo4j import script, optional D3 static export.

### Phase 2 (explicitly outside the MVP)
Full-text pipeline (PyMuPDF -> optional GROBID), Unpaywall/CORE resolution, and evaluation
experiment #4 (full-text vs abstract-only extraction quality) which justifies that added complexity.

---

## 4. Cross-cutting rules (built in P0, not retrofitted)

- **Prompt versioning** — each prompt module is hashed into the LLM cache key, so editing a prompt
  invalidates exactly the affected calls and nothing else.
- **Determinism** — temperature 0 for extraction; the corpus snapshot is committed so evaluation
  numbers are reproducible across runs.
- **Rate limits** — Semantic Scholar anonymous access is roughly 1 req/s. Concurrency semaphore,
  exponential backoff, and per-stage resume all exist from P1.
- **Hallucination guards** — temporal ordering (P4), citation-ID validation (P5), and relation
  precision measured on a 30-50 edge manual sample (P8).
- **Cost visibility** — token counts and estimated cost accumulated per stage, printed at the end of
  every run.

---

## 5. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Semantic Scholar / OpenAlex 429s stall a build | High | SQLite cache + throttle + per-stage resume, live from P0/P1 |
| Concept over-merge corrupts lineage answers | High | LLM judge on borderline pairs only; manual 10-pair gate in P3 |
| LLM hallucinates `EXTENDS` edges | High | Temporal constraint (P4) + citation-grounded prompt + measured precision (P8) |
| Gemini quota or cost overrun | Medium | Flash-class model for extraction, pro-class only for synthesis; per-stage cost report |
| No SerpApi -> recent preprints missed | Medium | arXiv/DBLP/CrossRef coverage; P1 coverage report names the blind spot explicitly |
| Entity-resolution embeddings need a local model | Low | Gemini `text-embedding` via the existing key; no torch install |
| Textual misbehaves on legacy conhost | Low | Documented requirement: Windows Terminal |
| Concept drift makes evaluation meaningless | Medium | Frozen, committed corpus snapshot for all eval runs |

---

## 6. Commands

```bash
rla build --title "Graph-based agent architectures"   # P1-P4: corpus + graph
rla ask "how did graph attention networks evolve?"    # P5: single question
rla report                                          # P6: research done + gaps
rla run --jsonl                                     # P7: headless event stream
rla tui                                             # P7: Kiro-style terminal UI
rla eval                                            # P8: metrics + baseline comparison
```

---

## 7. Effort estimate

Solo, ~14 working days for P0-P9:

| Phase | Days |
|---|---|
| P0 Foundation | 1 |
| P1 Acquisition | 2 |
| P2 Extraction | 2 |
| P3 Entity resolution | 1.5 |
| P4 Graph build | 1 |
| P5 Traversal + answers | 2 |
| P6 Gap analysis | 1.5 |
| P7 Orchestrator + TUI | 2 |
| P8 Evaluation | 2 |
| P9 Polish | 1 |
| **Phase 2 (full text)** | **+3** |

---

## 8. Demo topic

**"Graph-based agent architectures"** — chosen because it sits inside this project's own domain, is
current enough to have live citations (MAGMA, G-Designer, Graph-of-Agents), and yields a corpus small
enough (40-100 papers) to hand-label for the P8 ground truth.
