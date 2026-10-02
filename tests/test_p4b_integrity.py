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
        paper = Paper(id=pid, title=f"T for {pid}", year=2024, abstract=f"{abstract} for {pid}")
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
