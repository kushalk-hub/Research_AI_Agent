# Data Integrity and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it impossible to build a graph from an extraction store that belongs to a different corpus, and reconcile the committed data so every data file describes the same corpus.

**Architecture:** `ExtractionStore` is keyed by `paper_hash`, so a stale entry is simply one whose `paper_id` is absent from the current corpus. The reconciler reports that set; the graph stage refuses to silently drop the relations those entries would have produced; and a read-only `rla status` command tells an operator exactly what is stale and what is missing before anything is run.

**Tech Stack:** Python 3.12, pydantic, pytest + pytest-asyncio (`asyncio_mode = "auto"`), ruff (line-length 100).

**Related:** `PLAN.md` P4, §5 risk register. Independent of the P12 plan — no provider work is required.

## Global Constraints

- Run everything through `.\.venv\Scripts\python.exe`.
- Tests must not read the developer's `.env`; `tests/conftest.py` already isolates both the file and any exported `RLA_*` variables.
- `data/corpus.json`, `data/extractions.jsonl` and `data/concepts.json` are committed **on purpose** so evaluation numbers reproduce. Do not regenerate or reformat them casually, and never commit them in a state that disagrees with itself.
- Every silent-drop path in the graph builder must become a counted, reported number. A count that is reported is fine; a count that is discarded is the defect.
- This plan does **not** attempt to make gap analysis produce output. `PLAN.md` P2 records that all 26 stored extractions have an empty `stated_limitation`; reconciliation supplies more data to diagnose that, it does not fix it.

---

## Background: the current defect

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
   **silently**. The counter it returns is `added`, not `dropped`, so the loss is invisible.
3. `resolve_concepts` is handed every stored extraction and builds `paper_years` from the
   *current* corpus. A stale extraction's paper id is not in that map, so
   `first_seen_year` comes out `None` for every affected concept.

Result: a graph with `CITES`, `EXTENDS` and `COMBINES_WITH` edges but **zero** `INTRODUCES`,
`USES` and `HAS_LIMITATION` edges; concepts with `year: null`; and `rla report` reporting
0 structural gaps because nothing can be old enough to count as abandoned. The graph on disk
says `135 nodes (30 papers, 105 concepts), 104 edges`.

---

## Task 1: Reconciler — report stale and missing entries

**Files:**
- Modify: `src/rla/store/extraction_store.py`
- Test: `tests/test_p4b_integrity.py` (create)

**Interfaces:**
- Consumes: `Corpus`, `ExtractionStore.all()`.
- Produces:
  - `rla.store.extraction_store.Reconciliation` — `@dataclass(slots=True)` with `stale: list[Extraction]`, `missing: list[str]`, `matched: int`, and `healthy: bool` property
  - `rla.store.extraction_store.reconcile(corpus: Corpus, store: ExtractionStore) -> Reconciliation`

- [ ] **Step 1: Write the failing tests**

```python
"""P4b: say when the extraction store belongs to a different corpus.

This is the check whose absence let a graph be built from 26 extractions of one
corpus and a 30-paper corpus of another, with every loss silent.
"""

from __future__ import annotations

from rla.models import Corpus, Paper
from rla.store.extraction_store import ExtractionStore, reconcile


def corpus(*ids: str) -> Corpus:
    papers = []
    for pid in ids:
        paper = Paper(id=pid, title="T", year=2024, abstract="text")
        paper.ensure_hash()
        papers.append(paper)
    return Corpus(title="t", papers=papers)


def store_with(tmp_path, papers: list[Paper]):
    from rla.models import Extraction

    store = ExtractionStore(tmp_path / "x.jsonl")
    for paper in papers:
        extraction = Extraction(
            paper_id=paper.id,
            paper_hash=paper.ensure_hash(),
            summary="s",
        )
        store.add(extraction)
    return store


def test_a_store_matching_the_corpus_is_healthy(tmp_path):
    papers = list(corpus("p1", "p2").papers)
    report = reconcile(corpus("p1", "p2"), store_with(tmp_path, papers))
    assert report.healthy is True
    assert report.stale == []
    assert report.missing == []


def test_entries_for_papers_outside_the_corpus_are_stale(tmp_path):
    papers = list(corpus("old1", "old2").papers)
    report = reconcile(corpus("new1", "new2"), store_with(tmp_path, papers))

    assert report.healthy is False
    assert [e.paper_id for e in report.stale] == ["old1", "old2"]
    assert sorted(report.missing) == sorted(p.id for p in corpus("new1", "new2").papers)


def test_partial_overlap_reports_both_directions(tmp_path):
    papers = list(corpus("shared", "old").papers)
    report = reconcile(corpus("shared", "new"), store_with(tmp_path, papers))

    assert [e.paper_id for e in report.stale] == ["old"]
    assert report.missing == ["new"]


def test_an_empty_store_is_stale_free_but_incomplete(tmp_path):
    """Not an error: a first run has nothing extracted yet."""
    store = ExtractionStore(tmp_path / "empty.jsonl")
    report = reconcile(corpus("p1"), store)

    assert report.stale == []
    assert report.missing == ["p1"]
    assert report.healthy is False


def test_an_empty_corpus_with_a_populated_store_is_all_stale(tmp_path):
    papers = list(corpus("a", "b").papers)
    report = reconcile(corpus(), store_with(tmp_path, papers))
    assert len(report.stale) == 2


def test_the_report_says_how_to_fix_itself(tmp_path):
    papers = list(corpus("old").papers)
    report = reconcile(corpus("new"), store_with(tmp_path, papers))
    assert "rla run" in report.advice
    assert "prune" in report.advice
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

    `stale` is the dangerous direction: entries for papers that are not in the
    corpus. They still feed the graph builder, and every paper-to-concept
    relation they carry is dropped there because its endpoint does not exist. The
    result is a graph that looks built and is missing its whole paper-to-concept
    layer.
    """

    stale: list[Extraction] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    matched: int = 0

    @property
    def healthy(self) -> bool:
        return not self.stale and not self.missing

    @property
    def advice(self) -> str:
        parts: list[str] = []
        if self.stale:
            parts.append(
                f"prune {len(self.stale)} extraction(s) for papers that are not in the "
                f"corpus (they belong to an older build)"
            )
        if self.missing:
            parts.append(
                f"extract {len(self.missing)} corpus paper(s) that have no extraction"
            )
        if not parts:
            return "the extraction store and the corpus agree"
        return "; ".join(parts) + " - run `rla run` to rebuild, or prune with `rla status --prune`"


def reconcile(corpus: Corpus, store: ExtractionStore) -> Reconciliation:
    """Compare the store against the corpus, in both directions."""
    wanted = {paper.id for paper in corpus.papers}
    have = {paper.id for paper in corpus.papers}
    stored = store.all()

    report = Reconciliation(
        stale=[e for e in stored if e.paper_id not in wanted],
        missing=[pid for pid in wanted if pid not in {e.paper_id for e in stored}],
    )
    report.matched = len(stored) - len(report.stale)
    del have
    return report
```

Remove the unused `have`/`del have` lines before committing — they are shown here only to
make the two directions explicit.

Add the imports this needs: `from dataclasses import dataclass, field` and
`from rla.models import Corpus, Extraction`.

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
git commit -m "Add a reconciler that reports stale and missing extractions"
```

## Task 2: Stop the silent drop

**Files:**
- Modify: `src/rla/store/graph_store.py`
- Modify: `src/rla/pipeline/graph_build.py`
- Test: additions to `tests/test_p0_graph.py` and `tests/test_p4_graph_build.py`

**Interfaces:**
- Consumes: `Reconciliation` (Task 1).
- Produces:
  - `graph_store.GraphBuildCounts` — `@dataclass(slots=True)` with `citations: int`, `added: int`, `skipped_missing_endpoint: int`, `duplicate: int`
  - `graph_store.build_graph(...) -> tuple[Graph, GraphBuildCounts, list[dict[str, str]]]` — the third element is the temporal violations, so the caller can still assert the invariant

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_p0_graph.py


def test_relations_with_an_absent_endpoint_are_counted_not_discarded(tmp_path):
    """The amplifier behind the stale-store defect: a relation whose endpoint is
    not in the graph used to be skipped silently, so a graph built from the wrong
    extraction store looked complete."""
    from rla.models import Concept, EdgeType, Paper, Relation
    from rla.store.graph_store import build_graph

    graph, counts, violations = build_graph(
        [Paper(id="in-corpus", title="P", year=2024)],
        [Concept(id="c:real", name="Real", first_seen_year=2020)],
        [
            Relation(source_id="c:real", target_id="c:other", edge_type=EdgeType.EXTENDS),
            Relation(source_id="ghost", target_id="c:real", edge_type=EdgeType.USES),
        ],
    )

    assert counts.added == 1
    assert counts.skipped_missing_endpoint == 1
    assert "ghost" in {n for n in graph.nodes}
```

```python
# append to tests/test_p4_graph_build.py


def test_the_graph_stage_reports_a_stale_store_as_a_warning(tmp_path):
    """A store that describes a different corpus must never produce a quiet
    success. The stage already knows `papers_without_extraction`; it must say so
    in the event, not only in a payload nobody reads."""
    import asyncio

    from rla.config import get_settings
    from rla.models import Concept, Corpus, Paper
    from rla.pipeline.graph_build import build_graph_stage
    from rla.store.extraction_store import Extraction, ExtractionStore

    settings = get_settings().model_copy(update={"data_dir": tmp_path, "graph_dir": tmp_path / "graph"})
    settings.graph_dir.mkdir(parents=True, exist_ok=True)

    corpus = Corpus(title="t", papers=[Paper(id="current", title="P", year=2024, abstract="x")])
    stale = Extraction(paper_id="from-an-old-corpus", paper_hash="deadbeef", summary="s")

    events = asyncio.run(
        _collect(
            build_graph_stage(
                corpus,
                [Concept(id="c:a", name="A", first_seen_year=2020)],
                [stale],
                settings.graph_json,
                settings.graph_graphml,
            )
        )
    )
    final = events[-1]
    assert final.payload["stale_extractions"] == 1
    assert any(e.kind in ("warn", "error") for e in events)


async def _collect(agen):
    return [e async for e in agen]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p0_graph.py -q -k "absent_endpoint"`
Expected: FAIL — `build_graph` returns a 2-tuple, not a 3-tuple.

- [ ] **Step 3: Count instead of discarding**

In `src/rla/store/graph_store.py`, replace `add_relations` and `build_graph`:

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
    """Add LLM-derived edges. A relation with an endpoint that is not in the graph
    is counted and skipped, never silently discarded."""
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
    return graph, counts, [
        {"source": s, "target": t, "edge": str(e)} for s, t, e in dropped
    ]
```

`build_graph` currently returns `(graph, report_dict)` and has **seven** call sites that unpack
two values. All of them must be updated to unpack three:

| file:line | current |
|---|---|
| `src/rla/pipeline/graph_build.py:213` | `graph, report = build_graph(papers, concepts, relations)` |
| `tests/conftest.py:84` | `graph, report = build_graph(papers, concepts, relations)` |
| `tests/test_p0_graph.py:17` | `graph, _report = build_graph(...)` |
| `tests/test_p0_graph.py:28` | `graph, report = build_graph(papers, [], [])` |
| `tests/test_p0_graph.py:36` | `graph, _ = build_graph(papers, [], [])` |
| `tests/test_p0_graph.py:41` | `graph, report = build_graph(...)` |
| `tests/test_p0_graph.py:52` | `graph, report = build_graph(...)` |

The report dict's keys are renamed, so any reader of them must be updated too:

| old key | new |
|---|---|
| `report["citations"]` | `counts.citations` |
| `report["derived_edges"]` | `counts.added` |
| `report["temporal_violations_dropped"]` | `len(violations)` |
| `report["temporal_violations"]` | `violations` |

Update `tests/conftest.py`'s `graph_and_papers` fixture, which tests destructure as
`(graph, papers, report)`:

```python
    graph, counts, violations = build_graph(papers, concepts, relations)
    return graph, papers, {
        "counts": counts,
        "temporal_violations": violations,
        "citations": counts.citations,
        "derived_edges": counts.added,
    }
```

The renamed keys are kept in the fixture's dict so the existing tests that assert on them keep
working unchanged.

- [ ] **Step 4: Report the staleness from the stage**

In `src/rla/pipeline/graph_build.py`, `build_research_graph` currently does
`graph, report = build_graph(...)` and then `report.update({...})`. Change it to the
three-value form, rebuild the report dict from `counts`, and add the staleness fields:

```python
    relations, unresolved = collect_relations(extractions, concepts)
    graph, counts, violations = build_graph(papers, concepts, relations)

    extracted_ids = {e.paper_id for e in extractions}
    by_type = Counter(str(r.edge_type) for r in relations)
    report: dict[str, Any] = {
        "citations": counts.citations,
        "derived_edges": counts.added,
        "skipped_missing_endpoint": counts.skipped_missing_endpoint,
        "duplicate_relations": counts.duplicate,
        "temporal_violations_dropped": len(violations),
        "temporal_violations": violations,
    }

    in_corpus = {p.id for p in papers}
    stale = [e.paper_id for e in extractions if e.paper_id not in in_corpus]
    report["stale_extractions"] = len(stale)
    report["stale_extraction_ids"] = sorted(set(stale))[:20]
    report.update({
`build_graph_stage`, after the existing event, emit a warning when anything was refused:

```python
    stale = report.get("stale_extractions", 0)
    skipped = report.get("skipped_missing_endpoint", 0)
    if stale or skipped:
        yield event(
            Phase.GRAPH,
            f"{stale} stored extraction(s) belong to a different corpus and "
            f"{skipped} relation(s) were dropped for a missing endpoint; "
            "the graph is missing its paper-to-concept layer. Run `rla status` "
            "for how to reconcile.",
            kind="warn",
            stale_extractions=stale,
            skipped_missing_endpoint=skipped,
        )
```

- [ ] **Step 5: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/store/graph_store.py src/rla/pipeline/graph_build.py tests/conftest.py tests/test_p0_graph.py tests/test_p4_graph_build.py
git commit -m "Count refused graph relations and warn when the extraction store is stale"
```

## Task 3: `rla status` — diagnose without running

**Files:**
- Modify: `src/rla/cli.py`
- Test: additions to `tests/test_p4b_integrity.py`

**Interfaces:**
- Consumes: `reconcile` (Task 1).
- Produces: `rla status [--prune]` command.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_reports_the_mismatch_without_running_anything(capsys, tmp_path):
    """Read-only: an operator must be able to see the problem before spending a
    single request."""
    from rla.cli import status_command

    papers = list(corpus("old").papers)
    store = store_with(tmp_path, papers)
    report = reconcile(corpus("new"), store)
    assert "old" in report.advice
```

The command is exercised through `typer.testing.CliRunner` in the same file:

```python
from typer.testing import CliRunner

def test_the_status_command_renders_the_reconciliation(tmp_path, monkeypatch):
    from rla.cli import app

    settings = Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                        raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph")
    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)
    (tmp_path / "extractions.jsonl").write_text("", encoding="utf-8")

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "extraction" in result.stdout.lower()


def test_prune_removes_entries_for_papers_outside_the_corpus(tmp_path):
    from rla.models import Corpus
    from rla.store.extraction_store import ExtractionStore, prune_stale

    papers = list(corpus("keep", "drop").papers)
    store = store_with(tmp_path, papers)
    target = Corpus(title="t", papers=[p for p in papers if p.id == "keep"])

    removed = prune_stale(target, store)

    assert removed == ["drop"]
    assert {e.paper_id for e in store.all()} == {"keep"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Expected: `ImportError: cannot import name 'prune_stale'`.

- [ ] **Step 3: Add `prune_stale`**

In `src/rla/store/extraction_store.py`, add `prune` to `ExtractionStore`:

```python
    def rewrite(self, extractions: Iterable[Extraction]) -> int:
        """Replace the file's contents atomically-ish, and return the row count.

        Used by pruning. `add` appends, so pruning has to rewrite; doing it in one
        write means an interrupted prune cannot leave a half-deleted store.
        """
        kept = list(extractions)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "".join(e.model_dump_json() + "\n" for e in kept), encoding="utf-8"
        )
        self._by_hash = {e.paper_hash: e for e in kept}
        return len(kept)


def prune_stale(corpus: Corpus, store: ExtractionStore) -> list[str]:
    """Drop extractions whose papers are not in `corpus`. Returns the removed ids."""
    wanted = {paper.id for paper in corpus.papers}
    keep = [e for e in store.all() if e.paper_id in wanted]
    removed = sorted({e.paper_id for e in store.all()} - wanted)
    store.rewrite(keep)
    return removed
```

- [ ] **Step 4: Add the command**

In `src/rla/cli.py`:

```python
@app.command()
def status(
    prune: Annotated[
        bool, typer.Option("--prune", help="Delete extractions for papers not in the corpus.")
    ] = False,
) -> None:
    """Report whether the corpus, extraction store and graph describe each other.

    Read-only unless `--prune`. Costs nothing: no network, no model, no LLM budget.
    """
    from rla.models import Corpus
    from rla.store.extraction_store import ExtractionStore, reconcile

    settings = get_settings()
    if not settings.corpus_path.exists():
        console.print(f"[red]no corpus at[/] {settings.corpus_path}")
        raise typer.Exit(code=1)

    corpus = Corpus.model_validate_json(settings.corpus_path.read_text("utf-8"))
    store = ExtractionStore(settings.extractions_path)
    report = reconcile(corpus, store)

    table = Table(title="rla status", show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("value")
    table.add_row("corpus papers", str(len(corpus.papers)))
    table.add_row("stored extractions", str(len(store)))
    table.add_row("matched", str(report.matched))
    table.add_row("stale", f"[red]{len(report.stale)}[/]" if report.stale else "0")
    table.add_row("missing", f"[yellow]{len(report.missing)}[/]" if report.missing else "0")
    graph = load_graph(settings.graph_json) if settings.graph_json.exists() else None
    table.add_row("graph nodes", str(graph.number_of_nodes()) if graph else "[dim]none[/]")
    table.add_row("graph edges", str(graph.number_of_edges()) if graph else "[dim]none[/]")
    console.print(table)

    if report.healthy:
        console.print("[green]the corpus, extraction store and graph agree[/]")
        return

    console.print(f"[yellow]{report.advice}[/]")
    if not prune:
        console.print("[dim]re-run with --prune to delete the stale entries[/]")
        return

    from rla.store.extraction_store import prune_stale

    removed = prune_stale(corpus, store)
    console.print(f"[green]pruned {len(removed)} stale extraction(s)[/]")
    console.print("[dim]re-run `rla run` to extract the missing papers[/]")
```

- [ ] **Step 5: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/cli.py src/rla/store/extraction_store.py tests/test_p4b_integrity.py
git commit -m "Add a read-only rla status command that diagnoses data staleness"
```

## Task 4: Reconcile the committed data

This is the task that makes the data mean something. It is a run, not code — but it has an
acceptance check that must pass before any of `data/` is committed again.

**Files:**
- Modify: `data/corpus.json`, `data/extractions.jsonl`, `data/concepts.json`
- Test: `tests/test_p4b_integrity.py` gains a data-consistency test that runs in CI

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: a mutually consistent data set, and a committed invariant.

- [ ] **Step 1: Write the consistency test first**

```python
def test_the_committed_store_belongs_to_the_committed_corpus():
    """Not a tmp_path test: this asserts the *committed* data agrees with itself.

    These three files are committed on purpose so evaluation numbers reproduce.
    That only holds while they describe the same corpus, so the invariant is a
    test rather than a convention.
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
    report = reconcile(corpus, ExtractionStore(settings.extractions_path))

    assert report.stale == [], (
        f"{len(report.stale)} committed extraction(s) are for papers that are not "
        f"in the committed corpus: {sorted({e.paper_id for e in report.stale})[:5]}"
    )
```

Note the `if not settings.corpus_path.exists(): return` guard: a fresh clone has no
`data/graph/`, but `corpus.json` **is** committed, so on CI this test is live.

- [ ] **Step 2: Run it and watch it fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p4b_integrity.py -q -k "committed"`
Expected: FAIL with 26 stale paper ids. That failure is the defect, stated.

- [ ] **Step 3: Diagnose before changing anything**

```powershell
rla status
```

Read the output. Confirm which direction is wrong:

- **Stale ≫ missing** — the store is from an older, larger build. The corpus is fine;
  prune and re-extract.
- **Stale = 0, missing = corpus size** — the store was never written for this corpus.
  Re-extract in full.
- **Both non-zero** — a rebuild was interrupted. Prune, then re-extract.

Record which case it was in the commit message. This is the kind of fact that is worth
knowing later and worthless if guessed.

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
**45 minutes**. After P12a it is ~8s per paper, about 4 minutes for the same corpus. Run it
in the background, or wait for P12a — the plan is identical either way.

- [ ] **Step 5: Verify the end state before committing**

```powershell
rla status
```

The acceptance condition:

```
corpus papers          30
stored extractions     30
matched                30
stale                  0
missing                0
```

Then check the graph actually gained the layer it was missing:

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

**Expected: `with year: 30 of 30`** or close to it. If years are still null, `paper_years`
lookup is still failing and the structural-gap half of `rla report` will remain empty.

- [ ] **Step 6: Run the full suite, then commit the data**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add data/corpus.json data/extractions.jsonl data/concepts.json tests/test_p4b_integrity.py
git commit -m "Reconcile the extraction store with the corpus

The committed store and corpus described different corpora (26 extractions, zero
shared paper ids), so the graph silently lost its entire paper-to-concept layer
and every concept's first_seen_year was null.

Stale entries pruned, all 30 corpus papers extracted, graph rebuilt. The invariant
is now a test rather than a convention."
```

---

## What this plan does not fix

State these plainly in the commit message and to the user, so reconciliation is not mistaken
for the whole job.

- **Gap analysis will still produce nothing.** `PLAN.md` P2: all 26 stored extractions have an
  empty `stated_limitation`, so the per-paper limitation table is empty and the synthesised
  gap section has no input. Reconciliation gives 30 extractions instead of 26, which is a
  better sample for diagnosing whether `is_prior_work_limitation` is over-firing — but it is
  diagnostic value, not a fix. The polarity filter needs its own investigation.
- **`rla eval` will still report `NOT MEASURED`.** The reference set is 0% hand-labelled and
  no amount of corpus repair changes that. See `PLAN.md` P8.
- **Citation coverage at 30 papers is sparse.** `CITES` edges only survive when both endpoints
  are inside the corpus, so a small corpus has a thin citation layer regardless of extraction
  quality. Raising `RLA_TARGET_CORPUS_MAX` fixes that, at proportionally more extraction cost.

## Sequencing

1. **This plan (Tasks 1-3)** — independent of P12, about an hour of work. Do it first so the
   defect can never be silent again.
2. **Task 4** — can run now at ~45 minutes, or in ~4 minutes after P12a. Same steps either way.
3. **P12a** — provider routing; makes every future reconciliation cheap.
4. **P12b** — embedding providers; makes entity resolution local.
5. **Then revisit P2** with 30 real extractions in hand, which is finally enough to measure the
   polarity filter's false-positive rate rather than guess at it.