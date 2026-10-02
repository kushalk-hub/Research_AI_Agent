# Data Integrity and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse to build a graph from an extraction store that does not describe the current corpus, and reconcile the committed data so every data file describes the same corpus.

**Architecture:** `ExtractionStore` is keyed by `paper_hash`, so reconciliation is **hash-keyed, not id-keyed** — an entry is current only if its hash equals the corpus paper's *current* content hash. Two failure classes are distinguished and treated differently: an **integrity** failure (`stale` — the store belongs to a different corpus; `superseded` — an entry for a corpus paper whose content has since changed) **blocks** graph creation with an `error` and no write; a **coverage** failure (`missing` — a corpus paper with no current extraction) only **warns**, because that is an ordinary incomplete run. `add_relations` counts refused relations instead of discarding them, and a read-only `rla status` reports store, corpus and graph agreement without spending anything.

**Tech Stack:** Python 3.12, pydantic, networkx, pytest + pytest-asyncio (`asyncio_mode = "auto"`), ruff (line-length 100).

**Related:** `PLAN.md` P4 and §5 risk register. Independent of the P12 plan — no provider work is required.

## Global Constraints

- Run everything through `.\.venv\Scripts\python.exe`.
- Tests must not read the developer's `.env`; `tests/conftest.py` already isolates both the file and any exported `RLA_*` variables.
- `data/corpus.json`, `data/extractions.jsonl` and `data/concepts.json` are committed **on purpose** so evaluation numbers reproduce. Do not regenerate or reformat them casually, and never commit them in a state that disagrees with itself.
- Every silent-drop path must become a counted, reported number. A count that is reported is fine; a count that is discarded is the defect.
- Rewriting a store must be atomic: temp file, then `os.replace`. An interrupted prune that half-deletes the store is worse than no prune.
- This plan does **not** attempt to make gap analysis produce output. `PLAN.md` P2 records that all 26 stored extractions have an empty `stated_limitation`; reconciliation supplies more data to diagnose that, it does not fix it.

---

## Background: the defect, and a second route to it

The committed store and the committed corpus describe different corpora:

```
corpus.json        30 papers, title "Graph Neural Network"
extractions.jsonl  26 extractions, paper ids: f93cc5ab…, doi:10.3390/systems14010047, …
intersection       0
```

Three things follow, none of them reported anywhere:

1. `graph_build.build_research_graph` derives relations from **every** stored extraction. The
   concept→concept lineage edges survive, because both endpoints are concepts. The
   paper→concept edges are dropped, because their `paper_id` is not a node in the graph.
2. `store/graph_store.py:add_relations` drops any relation whose endpoint is absent,
   **silently**. It returns `added`, so the loss leaves no trace.
3. `resolve_concepts` is handed every stored extraction and builds `paper_years` from the
   *current* corpus. A stale entry's paper id is not in that map, so `first_seen_year`
   comes out `None` for every affected concept.

Result: a graph with `CITES`, `EXTENDS` and `COMBINES_WITH` edges but **zero** `INTRODUCES`,
`USES` and `HAS_LIMITATION` edges; concepts with `year: null`; and `rla report` reporting
0 structural gaps because nothing can be old enough to count as abandoned. The graph on disk
reads `135 nodes (30 papers, 105 concepts), 104 edges`.

### Why id-based reconciliation is not enough

There is a second, independent route to the same wrong graph, and it is the reason this plan
is hash-keyed. Verified:

```text
paper.abstract = "ORIGINAL TEXT"      -> hash 1ebb96be, extracted, stored
paper.abstract = "CORRECTED, RICHER"  -> hash 0b6e397f, store.get(0b6e397f) is None
                                         so extraction correctly re-runs and appends
```

The store now holds **two** entries for `paper_id == "p1"`: one current, one orphaned at the
old hash. A reconciler comparing `paper_id` sets sees `{"p1"} & {"p1"}` and reports healthy.
Meanwhile `build_graph` derives relations from **both**, adding edges derived from abstract
text that no longer exists — a concept that the paper may have dropped entirely.

Resume behaviour is correct here; the *reporting* is what is wrong. So reconciliation must
compare **hashes**, and must report a same-id-different-hash entry as its own failure class.

---

## Task 1: Reconciler — hash-keyed, two failure classes

**Files:**
- Modify: `src/rla/store/extraction_store.py`
- Test: `tests/test_p4b_integrity.py` (create)

**Interfaces:**
- Consumes: `Corpus`, `ExtractionStore.all()`, `Paper.ensure_hash()`.
- Produces:
  - `Reconciliation` — `@dataclass(slots=True)` with fields `stale: list[Extraction]`, `superseded: list[Extraction]`, `missing: list[str]`, `matched: int`; properties `intact: bool`, `healthy: bool`, `advice: str`
  - `reconcile(corpus: Corpus, store: ExtractionStore) -> Reconciliation`

**Semantics**

| class | meaning | severity |
|---|---|---|
| `stale` | entry's `paper_id` is not in the corpus at all | integrity — blocks the graph |
| `superseded` | entry's `paper_id` **is** in the corpus, but its hash is not that paper's current hash | integrity — blocks the graph |
| `missing` | a corpus paper whose current hash has no entry | coverage — warns |
| `matched` | count of corpus papers whose **current hash** is a key in the store | — |

`intact` = no stale and no superseded. `healthy` = `intact` and no missing. The graph gate uses
`intact`; the committed-data test uses `healthy`.

- [ ] **Step 1: Write the failing tests**

```python
"""P4b: say when the extraction store does not describe the current corpus.

This is the check whose absence let a graph be built from 26 extractions of one
corpus and a 30-paper corpus of another, with every loss silent.

Hash-keyed on purpose. Comparing paper ids alone reports an entry whose content
has since been superseded as healthy, while `build_graph` keeps deriving relations
from it -- a second, independent route to the same wrong graph.
"""

from __future__ import annotations

from rla.models import Corpus, Extraction, Paper
from rla.store.extraction_store import ExtractionStore, reconcile


def make_corpus(*ids: str, abstract: str = "text") -> Corpus:
    papers = []
    for pid in ids:
        paper = Paper(id=pid, title="T", year=2024, abstract=abstract)
        paper.ensure_hash()
        papers.append(paper)
    return Corpus(title="t", papers=papers)


def fill(tmp_path, papers, *, paper_ids=None) -> ExtractionStore:
    store = ExtractionStore(tmp_path / "x.jsonl")
    for index, paper in enumerate(papers):
        store.add(
            Extraction(
                paper_id=(paper_ids or [p.id for p in papers])[index],
                paper_hash=paper.ensure_hash(),
                summary="s",
            )
        )
    return store


# -- the healthy case ---------------------------------------------------------


def test_a_store_matching_the_corpus_is_healthy(tmp_path):
    target = make_corpus("p1", "p2")
    store = fill(tmp_path, target.papers)

    report = reconcile(target, store)

    assert report.healthy is True
    assert report.intact is True
    assert report.stale == []
    assert report.superseded == []
    assert report.missing == []
    assert report.matched == 2


def test_an_empty_store_is_intact_but_not_complete(tmp_path):
    """Not an integrity failure: a first run has extracted nothing yet."""
    report = reconcile(make_corpus("p1"), ExtractionStore(tmp_path / "empty.jsonl"))

    assert report.intact is True
    assert report.healthy is False
    assert report.missing == ["p1"]
    assert report.matched == 0


# -- integrity: wrong corpus --------------------------------------------------


def test_entries_for_papers_outside_the_corpus_are_stale(tmp_path):
    store = fill(tmp_path, make_corpus("old1", "old2").papers)
    report = reconcile(make_corpus("new1", "new2"), store)

    assert [e.paper_id for e in report.stale] == ["old1", "old2"]
    assert report.intact is False
    assert sorted(report.missing) == ["new1", "new2"]


def test_a_store_with_no_corpus_at_all_is_wholly_stale(tmp_path):
    store = fill(tmp_path, make_corpus("a", "b").papers)
    report = reconcile(make_corpus(), store)
    assert len(report.stale) == 2


# -- integrity: superseded content --------------------------------------------


def test_an_entry_whose_paper_content_changed_is_superseded(tmp_path):
    """The subtle case an id comparison misses.

    `Paper.ensure_hash` covers the abstract, so editing it changes the hash.
    Resume then re-extracts correctly -- but the old entry stays in the store with
    the SAME paper_id, and keeps feeding the graph builder.
    """
    before = make_corpus("p1", abstract="ORIGINAL TEXT")
    store = fill(tmp_path, before.papers)

    after = make_corpus("p1", abstract="CORRECTED, RICHER TEXT")
    store.add(
        Extraction(
            paper_id="p1",
            paper_hash=after.papers[0].ensure_hash(),
            summary="from corrected",
        )
    )

    report = reconcile(after, store)

    assert [e.paper_hash for e in report.stale] == [], "same id is not staleness"
    assert len(report.superseded) == 1, "but it is superseded"
    assert report.superseded[0].summary == "s"
    assert report.intact is False
    assert report.missing == [], "the current hash IS present"


def test_superseded_and_missing_are_reported_together(tmp_path):
    before = make_corpus("shared", "old")
    store = fill(tmp_path, before.papers)
    after = make_corpus("shared", "new", abstract="DIFFERENT TEXT")
    store.add(
        Extraction(
            paper_id="shared",
            paper_hash=after.papers[0].ensure_hash(),
            summary="from corrected",
        )
    )

    report = reconcile(after, store)

    assert [e.paper_id for e in report.stale] == ["old"]
    assert [e.paper_id for e in report.superseded] == ["shared"]
    assert report.missing == ["new"]
    assert report.intact is False


# -- counting -----------------------------------------------------------------


def test_matched_counts_papers_not_rows(tmp_path):
    """Duplicate entries for one paper must not inflate the matched count."""
    target = make_corpus("p1")
    paper = target.papers[0]
    store = ExtractionStore(tmp_path / "x.jsonl")
    for suffix in ("a", "b"):
        store.add(Extraction(paper_id="p1", paper_hash=paper.ensure_hash(), summary=suffix))

    report = reconcile(target, store)

    assert report.matched == 1, "one paper, one match -- not one per row"


def test_matched_is_an_id_intersection_not_a_survivor_count(tmp_path):
    """`len(stored) - len(stale)` would be wrong: rows and papers are different units."""
    target = make_corpus("p1", "p2")
    store = fill(tmp_path, target.papers)
    store.add(Extraction(paper_id="ghost", paper_hash="deadbeef", summary="s"))

    report = reconcile(target, store)

    assert report.matched == 2


# -- advice -------------------------------------------------------------------


def test_the_advice_distinguishes_the_two_failure_classes(tmp_path):
    stale_store = fill(tmp_path, make_corpus("old").papers)
    stale_advice = reconcile(make_corpus("new"), stale_store).advice
    assert "prune" in stale_advice
    assert "rla status" in stale_advice

    short_advice = reconcile(make_corpus("p1"), ExtractionStore(tmp_path / "e.jsonl")).advice
    assert "extract" in short_advice
    assert "prune" not in short_advice


def test_a_healthy_store_needs_no_advice(tmp_path):
    target = make_corpus("p1")
    assert "agree" in reconcile(target, fill(tmp_path, target.papers)).advice
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q`
Expected: collection error — `ImportError: cannot import name 'reconcile'`.

- [ ] **Step 3: Implement the reconciler**

Append to `src/rla/store/extraction_store.py`:

```python
@dataclass(slots=True)
class Reconciliation:
    """How the stored extractions relate to the current corpus.

    Two failure classes, deliberately kept apart because they deserve different
    responses:

    * **integrity** -- `stale` (the entry belongs to a different corpus) and
      `superseded` (the entry's paper is in the corpus but its content has since
      changed). Both mean the graph would be built from extractions that do not
      describe this corpus, so the graph stage refuses rather than warns.
    * **coverage** -- `missing`. An ordinary incomplete run. Warn, then proceed.

    `matched` counts PAPERS whose current content hash is stored, never rows.
    """

    stale: list[Extraction] = field(default_factory=list)
    superseded: list[Extraction] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    matched: int = 0

    @property
    def intact(self) -> bool:
        """Nothing in the store contradicts the corpus."""
        return not self.stale and not self.superseded

    @property
    def healthy(self) -> bool:
        """Intact AND fully covered. The committed-data invariant."""
        return self.intact and not self.missing

    @property
    def advice(self) -> str:
        parts: list[str] = []
        if self.stale:
            parts.append(
                f"delete {len(self.stale)} extraction(s) for papers that are not in the corpus"
            )
        if self.superseded:
            parts.append(
                f"delete {len(self.superseded)} extraction(s) whose paper content has "
                f"changed since extraction"
            )
        if self.missing:
            parts.append(
                f"extract {len(self.missing)} corpus paper(s) that have no current extraction"
            )
        if not parts:
            return "the extraction store and the corpus agree"
        return "; ".join(parts) + " - run `rla status --prune` then `rla run`"


def reconcile(corpus: Corpus, store: ExtractionStore) -> Reconciliation:
    """Compare the store against the corpus, hash-keyed, in both directions."""
    papers = list(corpus.papers)
    wanted_ids = {paper.id for paper in papers}
    current_hash = {paper.id: paper.ensure_hash() for paper in papers}
    stored_keys = {entry.paper_hash for entry in store.all()}

    report = Reconciliation(
        stale=[e for e in store.all() if e.paper_id not in wanted_ids],
        superseded=[
            e
            for e in store.all()
            if e.paper_id in wanted_ids and e.paper_hash != current_hash[e.paper_id]
        ],
        missing=[p.id for p in papers if current_hash[p.id] not in stored_keys],
    )
    report.matched = sum(1 for p in papers if current_hash[p.id] in stored_keys)
    return report
```

Add the imports this needs at the top of the file: `from dataclasses import dataclass, field`
and `from rla.models import Corpus, Extraction`.

- [ ] **Step 4: Run the tests, the full suite, lint**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

Expected: PASS / All checks passed.

- [ ] **Step 5: Commit**

```bash
git add src/rla/store/extraction_store.py tests/test_p4b_integrity.py
git commit -m "Add a hash-keyed reconciler separating integrity from coverage failures"
```

## Task 2: Block the graph on an integrity failure; count refusals

**Files:**
- Modify: `src/rla/store/graph_store.py`
- Modify: `src/rla/pipeline/graph_build.py`
- Modify: `src/rla/store/extraction_store.py` (`rewrite`, atomic)
- Modify: `tests/conftest.py`, `tests/test_p0_graph.py`
- Test: additions to `tests/test_p0_graph.py` and `tests/test_p4_graph_build.py`

**Interfaces:**
- Consumes: `reconcile` (Task 1).
- Produces:
  - `graph_store.GraphBuildCounts` — `@dataclass(slots=True)` with `citations: int`, `added: int`, `skipped_missing_endpoint: int`, `duplicate: int`
  - `graph_store.build_graph(papers, concepts, relations) -> tuple[Graph, GraphBuildCounts, list[dict[str, str]]]`
  - `ExtractionStore.rewrite(extractions) -> int`, atomic

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_p0_graph.py


def test_only_the_relation_whose_endpoints_exist_is_added(tmp_path):
    """Both relations are checked against the SAME node set.

    `c:other` does not exist, so that EXTENDS is refused; `ghost` does not
    exist, so that USES is refused too. One added, one refused -- and the
    unknown paper id is NOT materialised, because a refused relation is not a
    reason to invent a node.
    """
    from rla.models import Concept, EdgeType, Paper, Relation
    from rla.store.graph_store import build_graph

    graph, counts, violations = build_graph(
        [Paper(id="in-corpus", title="P", year=2024)],
        [
            Concept(id="c:real", name="Real", first_seen_year=2020),
            Concept(id="c:other", name="Other", first_seen_year=2021),
        ],
        [
            Relation(source_id="c:real", target_id="c:other", edge_type=EdgeType.EXTENDS),
            Relation(source_id="ghost", target_id="c:real", edge_type=EdgeType.USES),
        ],
    )

    assert counts.added == 1
    assert counts.skipped_missing_endpoint == 1
    assert "ghost" not in graph.nodes
    assert violations == []


def test_a_fully_unresolvable_relation_set_adds_nothing(tmp_path):
    from rla.models import Concept, EdgeType, Paper, Relation
    from rla.store.graph_store import build_graph

    graph, counts, _ = build_graph(
        [Paper(id="p", title="P", year=2024)],
        [Concept(id="c:real", name="Real", first_seen_year=2020)],
        [
            Relation(source_id="c:real", target_id="c:absent", edge_type=EdgeType.EXTENDS),
            Relation(source_id="ghost", target_id="c:real", edge_type=EdgeType.USES),
        ],
    )

    assert counts.added == 0
    assert counts.skipped_missing_endpoint == 2
```

```python
# append to tests/test_p4_graph_build.py


async def _collect(agen):
    return [e async for e in agen]


async def test_the_graph_stage_refuses_to_write_from_a_store_of_another_corpus(tmp_path):
    """The integrity policy, not a warning.

    `stale > 0` means the store describes a different corpus, so a graph built
    from it is wrong in a way no reader could detect. The stage must error and
    must NOT write graph.json.
    """
    from rla.config import get_settings
    from rla.models import Concept, Corpus, Extraction, Paper
    from rla.pipeline.graph_build import build_graph_stage
    from rla.store.extraction_store import ExtractionStore

    settings = get_settings().model_copy(
        update={"data_dir": tmp_path, "graph_dir": tmp_path / "graph"}
    )
    settings.ensure_dirs()
    store = ExtractionStore(tmp_path / "e.jsonl")
    store.add(
        Extraction(paper_id="from-an-old-corpus", paper_hash="deadbeef", summary="s")
    )

    corpus = Corpus(
        title="t", papers=[Paper(id="current", title="P", year=2024, abstract="x")]
    )
    events = await _collect(
        build_graph_stage(
            corpus,
            [Concept(id="c:a", name="A", first_seen_year=2020)],
            store.all(),
            settings.graph_json,
            settings.graph_graphml,
        )
    )

    assert any(e.kind == "error" for e in events)
    assert not settings.graph_json.exists(), "a graph must not be written from a stale store"


async def test_the_graph_stage_still_writes_when_only_coverage_is_incomplete(tmp_path):
    """Missing extractions are an ordinary incomplete run: warn, and build."""
    from rla.config import get_settings
    from rla.models import Concept, Corpus, Extraction, Paper
    from rla.pipeline.graph_build import build_graph_stage
    from rla.store.extraction_store import ExtractionStore

    settings = get_settings().model_copy(
        update={"data_dir": tmp_path, "graph_dir": tmp_path / "graph"}
    )
    settings.ensure_dirs()
    paper = Paper(id="current", title="P", year=2024, abstract="x")
    store = ExtractionStore(tmp_path / "e.jsonl")
    store.add(Extraction(paper_id=paper.id, paper_hash=paper.ensure_hash(), summary="s"))

    corpus = Corpus(
        title="t",
        papers=[paper, Paper(id="other", title="Q", year=2023, abstract="y")],
    )
    events = await _collect(
        build_graph_stage(
            corpus,
            [Concept(id="c:a", name="A", first_seen_year=2020)],
            store.all(),
            settings.graph_json,
            settings.graph_graphml,
        )
    )

    assert settings.graph_json.exists()
    assert not any(e.kind == "error" for e in events)
    assert any(e.kind == "warn" for e in events), "an incomplete corpus must say so"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p0_graph.py -q -k "endpoints or unresolvable"`
Expected: FAIL — `build_graph` returns a 2-tuple, so the 3-tuple unpack raises.

- [ ] **Step 3: Count instead of discarding**

In `src/rla/store/graph_store.py`, add:

```python
@dataclass(slots=True)
class GraphBuildCounts:
    """What was added, and what was refused.

    A refused relation is a *result*, not an oversight. Counting it is what turns
    "the graph is missing its paper-to-concept layer" from an invisible state into
    a number a reader can act on.
    """

    citations: int = 0
    added: int = 0
    skipped_missing_endpoint: int = 0
    duplicate: int = 0


def add_relations(graph: Graph, relations: Iterable[Relation], counts: GraphBuildCounts) -> int:
    """Add LLM-derived edges.

    A relation with an endpoint that is not in the graph is counted and skipped.
    It is never materialised as a node either: inventing one would assert that a
    paper we do not have exists.
    """
    for relation in relations:
        if not (graph.has_node(relation.source_id) and graph.has_node(relation.target_id)):
            counts.skipped_missing_endpoint += 1
            continue
        if graph.has_edge(relation.source_id, relation.target_id, key=str(relation.edge_type)):
            counts.duplicate += 1
            continue
        graph.add_edge(
            relation.source_id,
            relation.target_id,
            key=str(relation.edge_type),
            type=str(relation.edge_type),
            relation=str(relation.relation) if relation.relation else None,
            evidence=relation.evidence,
            confidence=relation.confidence,
            ground_truth=False,
        )
        counts.added += 1
    return counts.added
```

and replace `build_graph`:

```python
def build_graph(
    papers: Iterable[Paper],
    concepts: Iterable[Concept],
    relations: Iterable[Relation],
) -> tuple[Graph, GraphBuildCounts, list[dict[str, str]]]:
    papers = list(papers)
    graph = empty_graph()
    add_papers(graph, papers)
    add_concepts(graph, concepts)
    counts = GraphBuildCounts(citations=add_citation_edges(graph, papers))
    add_relations(graph, relations, counts)
    dropped = enforce_temporal_constraints(graph)
    violations = [{"source": s, "target": t, "edge": str(e)} for s, t, e in dropped]
    return graph, counts, violations
```

**Seven call sites unpack two values today and must unpack three:**

| file:line | current |
|---|---|
| `src/rla/pipeline/graph_build.py:213` | `graph, report = build_graph(papers, concepts, relations)` |
| `tests/conftest.py:84` | `graph, report = build_graph(papers, concepts, relations)` |
| `tests/test_p0_graph.py:17` | `graph, _report = build_graph(...)` |
| `tests/test_p0_graph.py:28` | `graph, report = build_graph(papers, [], [])` |
| `tests/test_p0_graph.py:36` | `graph, _ = build_graph(papers, [], [])` |
| `tests/test_p0_graph.py:41` | `graph, report = build_graph(...)` |
| `tests/test_p0_graph.py:52` | `graph, report = build_graph(...)` |

The report-dict keys are renamed too. Old → new: `citations` → `counts.citations`,
`derived_edges` → `counts.added`, `temporal_violations_dropped` → `len(violations)`,
`temporal_violations` → `violations`.

Update `tests/conftest.py`'s `graph_and_papers` fixture, which tests destructure as
`(graph, papers, report)`, keeping the old keys so existing assertions still pass:

```python
    graph, counts, violations = build_graph(papers, concepts, relations)
    return graph, papers, {
        "citations": counts.citations,
        "derived_edges": counts.added,
        "temporal_violations_dropped": len(violations),
        "temporal_violations": violations,
    }
```

- [ ] **Step 4: Gate the stage on integrity, not on coverage**

In `src/rla/pipeline/graph_build.py`, add the gate at the very top of
`build_graph_stage`, before any graph is built:

```python
    from rla.store.extraction_store import ExtractionStore, reconcile

    report_data = reconcile(corpus, ExtractionStore_from_list(extractions))
```

`reconcile` takes a store, but `build_graph_stage` receives a plain list. Give it an overload
that accepts either, so the gate works from the list it was handed:

```python
# in extraction_store.py, next to reconcile
def reconcile_extractions(corpus: Corpus, extractions: Iterable[Extraction]) -> Reconciliation:
    """`reconcile` for callers that hold a list rather than a store."""
    class _View:
        def __init__(self, items: list[Extraction]) -> None:
            self._items = list(items)

        def all(self) -> list[Extraction]:
            return self._items

    return reconcile(corpus, _View(extractions))  # type: ignore[arg-type]
```

Then, at the top of `build_graph_stage`, before `if not concepts:`:

```python
    integrity = reconcile_extractions(corpus, extractions)
    if not integrity.intact:
        yield event(
            Phase.GRAPH,
            f"refusing to build a graph: {len(integrity.stale)} stored extraction(s) belong "
            f"to a different corpus and {len(integrity.superseded)} describe superseded "
            f"paper content. A graph built now would be wrong in a way no reader could "
            f"detect. {integrity.advice}",
            kind="error",
            stale_extractions=len(integrity.stale),
            superseded_extractions=len(integrity.superseded),
            blocked=True,
        )
        return

    if integrity.missing:
        yield event(
            Phase.GRAPH,
            f"{len(integrity.missing)} corpus paper(s) have no extraction; building a "
            "partial graph",
            kind="warn",
            missing_extractions=len(integrity.missing),
            blocked=False,
        )
```

Because the gate `return`s, `save_graph` is never reached — no `graph.json`, no `graph.graphml`.
That is the behaviour the goal asks for, and `test_the_graph_stage_refuses_to_write_from_a_store_of_another_corpus`
asserts it.

In `build_research_graph`, change the `build_graph` call to the three-value form and fold the
counts into the report:

```python
    relations, unresolved = collect_relations(extractions, concepts)
    graph, counts, violations = build_graph(papers, concepts, relations)

    report: dict[str, Any] = {
        "citations": counts.citations,
        "derived_edges": counts.added,
        "skipped_missing_endpoint": counts.skipped_missing_endpoint,
        "duplicate_relations": counts.duplicate,
        "temporal_violations_dropped": len(violations),
        "temporal_violations": violations,
    }
    extracted_ids = {e.paper_id for e in extractions}
    by_type = Counter(str(r.edge_type) for r in relations)
    report.update({
        # ... the existing keys unchanged ...
    })
    return graph, report
```

Also emit a warning when relations were refused for a missing endpoint, since that is the
amplifier the original defect travelled through:

```python
    if report["skipped_missing_endpoint"]:
        yield event(
            Phase.GRAPH,
            f"{report['skipped_missing_endpoint']} relation(s) were dropped because an "
            "endpoint is not in the graph",
            kind="warn",
            skipped_missing_endpoint=report["skipped_missing_endpoint"],
        )
```

- [ ] **Step 5: Make `rewrite` atomic**

In `src/rla/store/extraction_store.py`, add `os` to the imports and replace the body Task 3
would have added (add it here, since the gate is useless if pruning can half-delete the store):

```python
    def rewrite(self, extractions: Iterable[Extraction]) -> int:
        """Replace the file's contents, atomically. Returns the row count.

        `add` appends, so pruning has to rewrite. A plain `write_text` is not
        enough: an interrupted prune would leave a half-deleted store, which is
        worse than not pruning at all because it is silent. Write beside the
        target and `os.replace`, which is atomic on Windows and POSIX.
        """
        kept = list(extractions)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for extraction in kept:
                handle.write(extraction.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        self._by_hash = {e.paper_hash: e for e in kept}
        return len(kept)
```

- [ ] **Step 6: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/store/graph_store.py src/rla/store/extraction_store.py src/rla/pipeline/graph_build.py tests/conftest.py tests/test_p0_graph.py tests/test_p4_graph_build.py
git commit -m "Refuse to build a graph from a mismatched store, and count refused relations"
```

## Task 3: `rla status` — diagnose all three artefacts without running anything

**Files:**
- Modify: `src/rla/cli.py`
- Modify: `src/rla/store/extraction_store.py` (`prune_stale`)
- Test: additions to `tests/test_p4b_integrity.py`

**Interfaces:**
- Consumes: `reconcile` (Task 1), `ExtractionStore.rewrite` (Task 2), `load_graph`, `NodeType.PAPER`.
- Produces: `prune_stale(corpus, store) -> list[str]`; `rla status [--prune]`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_p4b_integrity.py

from rla.cli import app
from typer.testing import CliRunner


def _settings(tmp_path, **kw):
    from rla.config import Settings

    base = {
        "_env_file": None,
        "gemini_api_key": "k",
        "data_dir": tmp_path,
        "raw_dir": tmp_path / "raw",
        "graph_dir": tmp_path / "graph",
    }
    base.update(kw)
    return Settings(**base)


def _seed_corpus_and_store(tmp_path):
    """Write a corpus.json and an extractions.jsonl that agree with each other."""
    target = make_corpus("current1", "current2")
    (tmp_path / "corpus.json").write_text(target.model_dump_json(), encoding="utf-8")
    store = ExtractionStore(tmp_path / "extractions.jsonl")
    for paper in target.papers:
        store.add(
            Extraction(paper_id=paper.id, paper_hash=paper.ensure_hash(), summary="s")
        )
    return target, store


def test_prune_removes_stale_and_superseded_entries(tmp_path):
    from rla.store.extraction_store import prune_stale

    before = make_corpus("keep", "drop", abstract="ORIGINAL")
    store = fill(tmp_path, before.papers)

    after = make_corpus("keep", "drop", abstract="CHANGED")
    store.add(
        Extraction(
            paper_id="keep", paper_hash=after.papers[0].ensure_hash(), summary="new"
        )
    )

    removed = prune_stale(after, store)

    assert sorted(removed) == ["drop", "keep@" + after.papers[0].ensure_hash()[:8]]
    assert {e.summary for e in store.all()} == {"new"}


def test_prune_leaves_a_healthy_store_untouched(tmp_path):
    from rla.store.extraction_store import prune_stale

    target = make_corpus("p1")
    store = fill(tmp_path, target.papers)
    assert prune_stale(target, store) == []
    assert len(store.all()) == 1


def test_the_status_command_reports_a_store_that_agrees(tmp_path, monkeypatch):
    _seed_corpus_and_store(tmp_path)
    monkeypatch.setattr("rla.cli.get_settings", lambda: _settings(tmp_path))

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "agree" in result.stdout


def test_status_reports_a_graph_that_does_not_match_the_corpus(tmp_path, monkeypatch):
    """Store and corpus can both be current while the graph on disk is from an
    older build. That is a real state, and checking only the store would call it
    healthy."""
    from rla.models import Paper
    from rla.store.graph_store import build_graph, save

    _seed_corpus_and_store(tmp_path)
    settings = _settings(tmp_path)

    graph, _counts, _violations = build_graph(
        [Paper(id="an-old-paper", title="Old", year=2020)], [], []
    )
    save(graph, settings.graph_json, settings.graph_graphml)

    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "graph stale papers" in result.stdout
    assert "an-old-paper" in result.stdout


def test_status_costs_nothing(tmp_path, monkeypatch):
    """No network, no model, no LLM budget -- it is a diagnosis command."""
    import rla.cli as cli

    _seed_corpus_and_store(tmp_path)
    monkeypatch.setattr("rla.cli.get_settings", lambda: _settings(tmp_path))
    called = []
    monkeypatch.setattr(cli, "build_client", lambda *a, **k: called.append(1))

    CliRunner().invoke(app, ["status"])

    assert called == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: `ImportError: cannot import name 'prune_stale'`.

- [ ] **Step 3: Add `prune_stale`**

In `src/rla/store/extraction_store.py`:

```python
def prune_stale(corpus: Corpus, store: ExtractionStore) -> list[str]:
    """Delete entries that do not describe the current corpus.

    Removes both `stale` and `superseded` entries. Returns human-readable labels
    so the operator can see what went: a paper id for staleness, `id@<hash>` for
    superseded content.
    """
    report = reconcile(corpus, store)
    doomed = {e.paper_hash for e in report.stale}
    doomed |= {e.paper_hash for e in report.superseded}
    labels = [e.paper_id for e in report.stale]
    labels += [f"{e.paper_id}@{e.paper_hash[:8]}" for e in report.superseded]

    store.rewrite([e for e in store.all() if e.paper_hash not in doomed])
    return sorted(labels)
```

- [ ] **Step 4: Add the command**

In `src/rla/cli.py`, after the `eval` command:

```python
@app.command()
def status(
    prune: Annotated[
        bool, typer.Option("--prune", help="Delete entries that do not describe this corpus.")
    ] = False,
) -> None:
    """Report whether the corpus, extraction store and graph describe each other.

    Read-only unless `--prune`. Costs nothing: no network, no model, no LLM budget.
    """
    from rla.models import Corpus, NodeType
    from rla.store.extraction_store import ExtractionStore, reconcile

    settings = get_settings()
    if not settings.corpus_path.exists():
        console.print(f"[red]no corpus at[/] {settings.corpus_path}")
        raise typer.Exit(code=1)

    corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
    store = ExtractionStore(settings.extractions_path)
    report = reconcile(corpus, store)
    corpus_ids = {paper.id for paper in corpus.papers}

    graph = load_graph(settings.graph_json) if settings.graph_json.exists() else None
    graph_ids: set[str] = set()
    if graph is not None:
        graph_ids = {
            node
            for node, data in graph.nodes(data=True)
            if data.get("type") == str(NodeType.PAPER)
        }
    graph_missing = sorted(corpus_ids - graph_ids) if graph is not None else []
    graph_stale = sorted(graph_ids - corpus_ids) if graph is not None else []

    table = Table(title="rla status", show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("value")
    table.add_row("corpus papers", str(len(corpus.papers)))
    table.add_row("stored extractions", str(len(store)))
    table.add_row("matched", str(report.matched))
    table.add_row("stale", _red_or_zero(len(report.stale)))
    table.add_row("superseded", _red_or_zero(len(report.superseded)))
    table.add_row("missing", _yellow_or_zero(len(report.missing)))
    table.add_row("graph nodes", str(graph.number_of_nodes()) if graph else "[dim]none[/]")
    table.add_row("graph edges", str(graph.number_of_edges()) if graph else "[dim]none[/]")
    table.add_row("graph missing papers", _yellow_or_zero(len(graph_missing)))
    table.add_row("graph stale papers", _red_or_zero(len(graph_stale)))
    console.print(table)

    if not report.intact:
        console.print(f"[red]{report.advice}[/]")
    elif graph_stale:
        console.print(
            "[red]the graph on disk contains papers that are not in the corpus; "
            "it is from an older build - re-run `rla run`[/]"
        )
    elif graph_missing:
        console.print(
            f"[yellow]the graph is missing {len(graph_missing)} corpus paper(s)[/]"
        )
    elif not report.missing:
        console.print("[green]the corpus, extraction store and graph agree[/]")
        return
    else:
        console.print(f"[yellow]{report.advice}[/]")

    if not prune:
        console.print("[dim]re-run with --prune to delete the stale and superseded entries[/]")
        return

    from rla.store.extraction_store import prune_stale

    removed = prune_stale(corpus, store)
    if removed:
        console.print(f"[green]pruned {len(removed)} entry(ies):[/] {', '.join(removed)}")
    console.print("[dim]re-run `rla run` to extract the missing papers[/]")
```

Add the two small helpers near `_print_event`:

```python
def _red_or_zero(count: int) -> str:
    return f"[red]{count}[/]" if count else "0"


def _yellow_or_zero(count: int) -> str:
    return f"[yellow]{count}[/]" if count else "0"
```

- [ ] **Step 5: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/cli.py src/rla/store/extraction_store.py tests/test_p4b_integrity.py
git commit -m "Add a read-only rla status that checks store, corpus and graph agreement"
```

## Task 4: Reconcile the committed data

A run, not code — but with an acceptance check that must pass before any of `data/` is
committed again.

**Files:**
- Modify: `data/corpus.json`, `data/extractions.jsonl`, `data/concepts.json`
- Test: `tests/test_p4b_integrity.py` gains a data-consistency test that runs in CI

- [ ] **Step 1: Write the invariant test first**

```python
def test_the_committed_store_describes_the_committed_corpus():
    """Not a tmp_path test: this asserts the *committed* data agrees with itself.

    These three files are committed on purpose so evaluation numbers reproduce.
    That only holds while they describe the same corpus, so the invariant is a
    test rather than a convention.

    Asserting only `stale == []` would pass with an EMPTY store, which is exactly
    the state this was written to catch. Assert the whole invariant.
    """
    import pathlib

    from rla.config import Settings
    from rla.models import Corpus
    from rla.store.extraction_store import ExtractionStore, reconcile

    root = pathlib.Path(__file__).resolve().parents[1]
    settings = Settings(_env_file=None, data_dir=root / "data")
    if not settings.corpus_path.exists():
        return
    corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
    store = ExtractionStore(settings.extractions_path)
    report = reconcile(corpus, store)

    assert report.stale == [], (
        f"{len(report.stale)} committed extraction(s) are for papers absent from the "
        f"corpus: {sorted({e.paper_id for e in report.stale})[:5]}"
    )
    assert report.superseded == [], (
        f"{len(report.superseded)} committed extraction(s) describe superseded content: "
        f"{sorted({e.paper_id for e in report.superseded})[:5]}"
    )
    assert report.missing == [], (
        f"{len(report.missing)} committed corpus paper(s) have no current extraction"
    )
    assert report.healthy is True
    assert report.matched == len(corpus.papers), (
        f"matched {report.matched} of {len(corpus.papers)} papers"
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q -k "committed"`
Expected: FAIL on the `stale` assertion with 26 paper ids. That failure is the defect, stated.

- [ ] **Step 3: Diagnose before changing anything**

```powershell
rla status
```

Read the output and record which direction is wrong in the commit message — this is worth
knowing later and worthless if guessed:

- **stale ≫ missing** — the store is from an older, larger build. Corpus is fine.
- **stale = 0, missing = corpus size** — the store was never written for this corpus.
- **superseded > 0** — a paper's abstract was enriched after extraction, leaving orphans.
- **any combination** — a rebuild was interrupted. Prune, then re-extract.

- [ ] **Step 4: Prune, then extract to completion**

```powershell
rla status --prune
rla run -t "Graph Neural Network" -q "How did graph attention networks evolve?"
```

`rla run` rewrites `data/corpus.json`, appends to `data/extractions.jsonl`, and rewrites
`data/concepts.json`. Extraction is content-hash resumable and the LLM cache is warm, so
**already-extracted papers cost nothing**; only genuinely new papers spend a request.

Expect this to be slow on the current configuration. Measured on this machine with the
LiteLLM-to-Ollama route, an extraction is **~85s per paper** (the OpenAI-compatible route
prepends ~3.4k tokens of format instructions to the prompt). A 30-paper corpus is roughly
**45 minutes**. After P12a it is ~8s per paper, about 4 minutes for the same corpus. Same
steps either way; run it in the background, or wait for P12a.

- [ ] **Step 5: Verify the end state before committing anything**

```powershell
rla status
```

Acceptance condition:

```
corpus papers          30
stored extractions     30
matched                30
stale                  0
superseded             0
missing                0
graph missing papers   0
graph stale papers     0
```

Then confirm the graph actually gained the layer it was missing:

```powershell
rla stats
```

`edges_INTRODUCES` and `edges_USES` must both be **non-zero**. If they are zero, extraction
is not producing concepts and reconciliation has not succeeded — stop and investigate rather
than committing.

Also confirm concepts now carry years:

```powershell
.\.venv\Scripts\python.exe -c "import json;d=json.load(open('data/concepts.json'));print('with year:',sum(1 for c in d['concepts'] if c.get('first_seen_year')),'of',len(d['concepts']))"
```

**Expected: `with year: 30 of 30`**, or close. Null years mean the `paper_years` lookup is
still failing, and the structural-gap half of `rla report` will stay empty.

- [ ] **Step 6: Full suite, then commit the data**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add data/corpus.json data/extractions.jsonl data/concepts.json tests/test_p4b_integrity.py
git commit -m "Reconcile the extraction store with the corpus

The committed store and corpus described different corpora (26 extractions, zero
shared paper ids), so the graph silently lost its entire paper-to-concept layer
and every concept's first_seen_year was null.

Stale entries pruned, all corpus papers extracted, graph rebuilt. The invariant is
now a test rather than a convention."
```

---

## Non-goals

- **A corpus fingerprint in the graph metadata.** Comparing the graph's paper ids to the
  corpus catches the mismatch, but a stored fingerprint would catch it in O(1) and would also
  detect "same papers, different content". `store/graph_store.save` writes only
  `{nodes, links}`, so this needs a format change. Worth doing later; not now.
- **Fixing the empty `stated_limitation`.** See below.
- **Changing how the store is keyed.** It is already keyed by `paper_hash`, which is the right
  identity. This plan makes the *reporting* hash-aware; it does not change storage.

## What this plan does not fix

State these plainly in the commit message and to the user, so reconciliation is not mistaken
for the whole job.

- **Gap analysis will still produce nothing.** `PLAN.md` P2: all 26 stored extractions have an
  empty `stated_limitation`, so the per-paper limitation table is empty and the synthesised gap
  section has no input. Reconciliation gives 30 extractions instead of 26, which is a better
  sample for diagnosing whether `is_prior_work_limitation` is over-firing — diagnostic value,
  not a fix.
- **`rla eval` will still report `NOT MEASURED`.** The reference set is 0% hand-labelled and no
  amount of corpus repair changes that. See `PLAN.md` P8.
- **Citation coverage at 30 papers is sparse.** `CITES` edges only survive when both endpoints
  are inside the corpus, so a small corpus has a thin citation layer regardless of extraction
  quality. Raising `RLA_TARGET_CORPUS_MAX` fixes that at proportionally more extraction cost.

## Sequencing

1. **This plan (Tasks 1-3)** — independent of P12, about an hour. Do it first, so the defect can
   never be silent again.
2. **Task 4** — can run now at ~45 minutes, or in ~4 minutes after P12a. Same steps either way.
3. **P12a** — provider routing; makes every future reconciliation cheap.
4. **P12b** — embedding providers; makes entity resolution local.
5. **Then revisit P2** with 30 real extractions in hand, which is finally enough to measure the
   polarity filter's false-positive rate rather than guess at it.