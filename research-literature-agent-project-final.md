# Intelligent Task-Specific AI Agent Built Using Graph-Based Architecture
## Project: Research Literature Assistant Agent

---

## 1. Purpose Statement

> An intelligent agent that takes a **research project title** as input, ingests relevant papers on that topic, constructs a **citation-and-concept graph** capturing how methods, ideas, and papers relate to and build on each other over time, and produces a structured report showing:
> 1. **What research has been done so far** (per paper and organized by theme)
> 2. **What gaps remain** — both per-paper stated limitations and synthesized, cross-paper open problems ("what's still unsolved till now")
>
> The reasoning is done by **traversing the graph**, not by flat summarization — this is what allows the agent to answer lineage questions ("how did technique X evolve?") and gap questions ("what hasn't been tried yet in Y?") accurately and with traceable citations.

### Why Graph-Based (not flat RAG/summarization)
Research knowledge is fundamentally relational — papers build on, replace, combine, and critique each other's methods over time. A flat vector store or chunk-based RAG system can retrieve similar text but cannot represent *lineage* (what led to what) or *sparse regions* (what's rarely been built upon) — both of which require graph structure to compute directly.

---

## 2. System Architecture (5 Layers)

### Layer 1 — Data Acquisition
- Input: a project title (e.g., "Graph-based Multi-Agent Reasoning for Task Planning")
- LLM expands the title into 3–5 search queries covering sub-topics/synonyms
- Fetch candidate papers from **multiple sources** (see Section 3 — Tech Stack) to avoid single-index blind spots
- **Snowball sampling**: expand 1–2 hops via references/citations of top seed papers
- Deduplicate across sources (match by DOI/title) and relevance-filter (LLM scores each abstract 1–5) down to a working corpus of **40–100 papers**

### Layer 2 — Concept Extraction
For every paper, one structured LLM call extracts:
- 1–2 sentence summary of what the paper does
- Method/technique(s) used (canonical name)
- What it builds on (prior methods/papers it extends)
- Relationship type: `extends`, `replaces`, `combines`, `applies-to-new-domain`, `critiques`
- Stated limitation / future work — pulled from the paper's actual **Limitations/Future Work section** when full text is available (not invented, not just guessed from the abstract)
- Inferred open problem based on the above

### Layer 3 — Graph Construction
Merge all extractions into one graph combining citation data (ground truth, no LLM needed) and concept relationships (LLM-derived).

### Layer 4 — Query-Time Reasoning Agent
Given a question or the default "research done + gaps" report request:
1. Classify question type (lineage / gap-finding / comparison / general / full-report)
2. Select a traversal strategy for that type
3. Execute traversal on the graph (returns a small relevant subgraph, not the whole graph)
4. Pass the subgraph to an LLM to generate a narrative, cited answer

### Layer 5 — Presentation (TUI)
Live terminal dashboard (Kiro-style) showing the agent's internal process in real time — not just the final answer. See Section 6.

---

## 3. Full Tech Stack

### 3a. Data Acquisition & Retrieval
| Tool | Role |
|---|---|
| **Semantic Scholar Graph API** | Primary source — papers, abstracts, authors, years, citation/reference links. Free, no scraping. |
| **OpenAlex API** | Free, open complement to Semantic Scholar. Strong citation coverage + built-in topic/concept tagging you can bootstrap your initial concept list from. |
| **Google Search API / SerpApi (Google Scholar results)** | Supplementary "did we miss anything" pass — catches very recent papers, preprints, and grey literature (workshop papers, technical reports) that citation-graph indexes miss. |
| **arXiv API** | Full paper text source for CS/AI papers when abstracts aren't enough for extraction. |
| **CrossRef API** | Resolves DOIs and fills in metadata gaps (venue, publication date) when other sources are incomplete. |
| **CORE API** | Aggregates open-access full-text papers across repositories — used to get full text beyond arXiv's coverage. |
| **Unpaywall API** | Given a DOI, finds a legal free full-text PDF link if one exists; pairs with CORE for full-text retrieval. |

### 3b. Full-Text Structuring
| Tool | Role |
|---|---|
| **GROBID** | Parses a PDF into structured sections (abstract, intro, methods, limitations, references) instead of raw text dump. Critical for reliable "stated limitation" extraction — pulling from the real Limitations/Future Work section, not the whole PDF. |

### 3c. Graph Storage
| Tool | Role |
|---|---|
| **Neo4j** | Graph database for `Paper`/`Concept` nodes and typed edges; supports real traversal queries (Cypher) and has built-in visualization (Neo4j Bloom). |
| **NetworkX** (alternative) | Lightweight, pure-Python graph library — good enough for 50–150 node graphs if you want to avoid running a separate DB server. |

### 3d. LLM / Reasoning
| Tool | Role |
|---|---|
| **LLM API** (e.g., Claude via Anthropic API) | Three jobs: (1) expand title into search queries, (2) extract concepts/relationships/limitations per paper, (3) turn a traversed subgraph into the final narrative, cited answer. |
| **Embeddings model** | Powers entity resolution — clustering similar concept names (e.g., "GAT" vs. "graph attention networks") by similarity before merging nodes. |

### 3e. Agent Orchestration
| Tool | Role |
|---|---|
| **LangGraph** | Manages the agent's own control flow as an explicit graph: search → fetch → extract → build graph → traverse → answer, with state passed between steps. |
| Custom Python state machine (alternative) | Lighter-weight option if avoiding the LangGraph dependency. |

### 3f. Frontend / Demonstration (TUI)
| Tool | Role |
|---|---|
| **Textual** (Python) | Builds the Kiro-style multi-panel terminal UI — status bar, live event log, graph tree view, streamed answer panel. |
| **Rich** | Powers formatted log lines, tables, and tree rendering (`rich.tree.Tree`) for lineage chains inside Textual. |

### 3g. Optional / Nice-to-have
| Tool | Role |
|---|---|
| **D3.js** | Browser-based interactive graph view as an alternative/supplement to the terminal tree, for a richer visual demo. |

---

## 4. Updated Data Acquisition Flow

1. **Semantic Scholar** (primary) + **OpenAlex** (secondary) → merged candidate list
2. **Google Search/SerpApi** → supplementary pass for recent/missed papers
3. **CrossRef** → clean up metadata gaps
4. For top-priority papers: **Unpaywall/CORE** → get full-text PDF
5. **GROBID** → parse PDF into structured sections
6. Concept extraction LLM call runs on **full sections** when available, falls back to **abstract** otherwise
7. Deduplicate across all sources (match by DOI/title) → final working corpus (40–100 papers)

---

## 5. Graph Schema

### Node Types
| Node | Properties |
|---|---|
| `Paper` | id, title, year, authors, abstract, venue |
| `Concept` | canonical name, short description, first-seen year, aliases (list) |

### Edge Types
| Edge | Meaning |
|---|---|
| `Paper --CITES--> Paper` | From citation data (ground truth) |
| `Paper --INTRODUCES--> Concept` | This paper originated the concept |
| `Paper --USES--> Concept` | This paper applies an existing concept |
| `Concept --EXTENDS--> Concept` | B builds on A |
| `Concept --REPLACES--> Concept` | B proposed as improvement/alternative to A |
| `Concept --COMBINES_WITH--> Concept` | B and C used together in some paper |
| `Paper --HAS_LIMITATION--> Concept` | Paper explicitly states this concept/combination is unsolved (powers gap detection) |

Having both `Paper` and `Concept` as separate node types (not just a citation network) is the key design decision that differentiates this from a plain citation-graph tool.

---

## 6. Traversal Logic (Question Type → Graph Algorithm)

| Question Type | Traversal Strategy |
|---|---|
| "What's the lineage of X?" | Find `Concept` node X → walk backward along `EXTENDS`/`REPLACES` for ancestry → walk forward for descendants → order by year |
| "What's unsolved in area Y?" | Find `Concept` nodes near Y → surface ones with few incoming `EXTENDS` edges (rarely built upon) or unresolved `HAS_LIMITATION` edges from recent papers |
| "How do X and Y compare?" | Find both concept nodes → find common ancestors + common co-usage papers → surface differences |
| "What are the major approaches to Z?" | Find `Concept` nodes with high in-degree (many `USES` edges) within Z subgraph → cluster |
| "Full report: research done + gaps" | Combine: chronological concept/paper walk (research so far) + aggregated gap synthesis (below) |

---

## 7. Aggregate Gap Analysis (the "till now" synthesis)

This is what elevates the project beyond "summarize each paper + list its gap":

1. **Cluster** individual paper-level stated gaps by theme (e.g., 6 papers saying "doesn't scale to large graphs" → one aggregate gap, not six)
2. **Structural gaps from the graph itself**: `Concept` nodes with very few `EXTENDS` edges pointing to them despite being old — "abandoned"/under-explored directions that no single paper states explicitly
3. **Rank gaps** by recency/frequency to distinguish genuinely open problems from ones already solved by a later paper in the corpus

Output: a per-paper gap table **plus** a synthesized "open problems across the field" section, each claim backed by citations.

---

## 8. TUI Demonstration Layer (Kiro-style)

Goal: expose the agent's internal process live, not just the final output — this is what makes the "graph reasoning" tangible.

### Panels
- **Top status bar**: current phase — `Searching → Fetching → Extracting → Building Graph → Traversing → Generating Answer` with progress indicator
- **Left panel — Live event log**: scrolling backend trace, e.g.
  ```
  [Search]   Generated 4 queries from title
  [Fetch]    Semantic Scholar: 18 papers | OpenAlex: 12 new | Google Scholar: 4 new
  [Fetch]    Deduplicated → 63 unique papers in corpus
  [FullText] Fetched full text for 22/63 papers via CORE/Unpaywall
  [Extract]  Paper 12/63: "G-Designer..." → 3 concepts, 1 limitation found
  [Graph]    Added edge: Concept("MAGMA") --EXTENDS--> Concept("RAG memory")
  [Traverse] Query type: LINEAGE → walking EXTENDS edges backward from "GAT"
  [Traverse] Found ancestry chain: 5 concepts, 7 papers
  ```
- **Center/right panel — Live graph view**: ASCII/Unicode tree of the traversal path as it's discovered (via `rich.tree.Tree`), plus live counters ("Graph: 63 papers, 41 concepts, 118 edges")
- **Bottom panel — Final answer**: synthesized narrative streamed token-by-token with inline citations

### Architecture Pattern: Event-Driven Pipeline
Backend pipeline should `yield` typed events instead of returning only a final result, so the TUI can subscribe and render live:

```python
def run_pipeline(title):
    yield Event("search", "Generating search queries...")
    queries = generate_queries(title)
    yield Event("search", f"Generated {len(queries)} queries")

    yield Event("fetch", "Fetching papers from Semantic Scholar, OpenAlex, Google Scholar...")
    papers = fetch_papers(queries)
    yield Event("fetch", f"{len(papers)} unique papers found")

    yield Event("fulltext", "Resolving full text via CORE/Unpaywall + GROBID...")
    papers = enrich_with_fulltext(papers)

    for i, paper in enumerate(papers):
        yield Event("extract", f"Paper {i + 1}/{len(papers)}: {paper.title[:40]}...")
        concepts = extract_concepts(paper)
        yield Event("graph", f"Added {len(concepts)} concept nodes")

    yield Event("traverse", "Running lineage traversal...")
    subgraph = traverse(graph, query)
    yield Event("answer", "Generating final answer...")
    answer = generate_answer(subgraph)
    yield Event("done", answer)
```

---

## 9. Hard Problems / Research Contribution

These are the genuinely difficult parts worth documenting as your project's contribution:

- **Entity resolution**: merging aliases like "GAT," "graph attention networks," "attention over graph nodes" into one Concept node — approach: embed name+description, cluster by cosine similarity, LLM as final judge on borderline merges
- **Multi-source deduplication**: the same paper appearing across Semantic Scholar, OpenAlex, and Google Scholar results needs to be merged by DOI/title matching before graph construction, or you'll get duplicate nodes
- **Relationship extraction accuracy**: LLMs can hallucinate `EXTENDS` edges that aren't really there — validate on a manual sample (30–50 edges) and report precision
- **Temporal correctness**: a paper can only extend concepts that existed *before* it — enforce publication-year ordering as a hard constraint/cleaning step
- **Scale vs. quality tradeoff**: more papers = richer graph but noisier extraction and higher cost — measure this explicitly (e.g., extraction accuracy at 30 vs. 100 papers)

---

## 10. Evaluation Plan

1. **Concept graph accuracy**: manually build a ground-truth graph for ~20 papers, compare against auto-extracted graph (precision/recall on nodes and edges)
2. **Answer quality vs. baseline**: for 10–15 lineage/gap questions, compare graph-traversal answers against a plain RAG-over-abstracts baseline, scored by human or LLM-as-judge rubric (correctness, completeness, citation accuracy)
3. **Gap-detection validity**: for flagged "understudied" concepts, check against expert intuition, or — best — check whether a *later* paper (excluded from the corpus) actually addressed that gap
4. **Full-text vs. abstract-only extraction**: compare limitation-extraction quality when using GROBID-parsed full sections vs. abstract-only, to justify the added pipeline complexity

---

## 11. Realistic Build Order / Milestones

1. Data pipeline: pull papers + citations from Semantic Scholar + OpenAlex for one topic, store raw
2. Add Google Search/SerpApi supplementary fetch + dedup logic
3. Add CORE/Unpaywall + GROBID full-text pipeline (can be added after MVP works on abstracts)
4. Concept extraction prompt + pipeline, iterate on output quality
5. Entity resolution / merge pass
6. Build graph in Neo4j/NetworkX, implement the traversal query types
7. Wire up LLM answer-generation on top of traversal results
8. Build evaluation set, run comparisons vs. baseline
9. Backend pipeline as event-emitting generator (headless first)
10. Build Textual TUI: status bar + event log panel, wired to event stream
11. Add tree/graph panel once traversal output is stable
12. Polish: colors per event type, progress bars, streamed final answer

---

## 12. Recommended First-Version Scope

- **One narrow topic** for the graph (40–100 papers) rather than general-purpose across all research — keeps concept extraction quality high and evaluation tractable
- **MVP data sources**: start with just Semantic Scholar (simplest, richest citation data); add OpenAlex, Google Search, and full-text (CORE/Unpaywall/GROBID) as later-phase enhancements once the core pipeline works
- **MVP gap analysis**: per-paper limitation table first, then layer on synthesized cross-paper gaps
- Suggested demo topic (fits your own project domain): *"Graph-based agent architectures"* — gives you real, current papers to test against (e.g., MAGMA, G-Designer, Graph-of-Agents)
