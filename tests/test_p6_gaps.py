"""P6 gate: gap analysis over a hand-built corpus.

Every stage is a pure function, so each is asserted directly. The cases that
matter most are the ones where the wrong answer looks plausible: a limitation
quoted from prior work, a gap that a later paper already closed, and a new
concept mistaken for an abandoned one.
"""

from __future__ import annotations

import pytest

from rla.models import Concept, EdgeType, Extraction, NodeType, Paper, Relation
from rla.pipeline.gaps import (
    RankedGap,
    build_gap_report,
    classify_theme,
    cluster_themes,
    paper_table,
    rank_gaps,
    render_report,
    render_table,
    structural_gaps,
    suppress_closed,
)
from rla.store.graph_store import build_graph

# -- the fixture ---------------------------------------------------------------

PAPERS = [
    Paper(id="p1", title="Graph Attention Networks", year=2018),
    Paper(id="p2", title="Scalable GAT", year=2021),
    Paper(id="p3", title="Graph RL Policies", year=2022),
    Paper(id="p4", title="Interpretable Graph Models", year=2023),
    Paper(id="p5", title="Old Direction", year=2016),
    Paper(id="p6", title="Recent but Unfollowed", year=2024),
]

#: Lineage runs parent -> child, so `attention -> gat` means GAT builds on
#: attention. `c:scale` is deliberately left with no lineage edge at all: old
#: enough to judge, and nothing in the corpus either builds on it or from it.
CONCEPTS = [
    Concept(id="c:attention", name="attention mechanisms", first_seen_year=2015),
    Concept(id="c:gat", name="graph attention networks", first_seen_year=2018),
    Concept(id="c:scale", name="sparse attention scaling", first_seen_year=2019),
    Concept(id="c:rl", name="graph RL policies", first_seen_year=2022),
    Concept(id="c:old", name="spectral graph methods", first_seen_year=2016),
    Concept(id="c:new", name="graph diffusion models", first_seen_year=2025),
]

RELATIONS = [
    Relation(source_id="c:attention", target_id="c:gat", edge_type=EdgeType.EXTENDS),
    Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p2", target_id="c:gat", edge_type=EdgeType.USES),
    Relation(source_id="p3", target_id="c:rl", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p5", target_id="c:old", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p6", target_id="c:new", edge_type=EdgeType.INTRODUCES),
]

EXTRACTIONS = [
    Extraction(
        paper_id="p1",
        paper_hash="h1",
        summary="Attention over graph neighbourhoods.",
        stated_limitation="It does not scale to graphs with more than a few million edges.",
        inferred_open_problem="Scaling attention to industrial graph sizes.",
    ),
    Extraction(
        paper_id="p2",
        paper_hash="h2",
        summary="Sparse attention for large graphs, addressing the memory cost of dense attention.",
        stated_limitation=(
            "The sparse pattern is chosen heuristically, so accuracy drops at extreme scaling."
        ),
    ),
    Extraction(
        paper_id="p3",
        paper_hash="h3",
        summary="Value decomposition over graph-structured multi-agent policies.",
        stated_limitation="The method cannot guarantee convergence in adversarial settings.",
    ),
    Extraction(
        paper_id="p4",
        paper_hash="h4",
        summary="Attention weights as explanations.",
        stated_limitation=(
            "The explanation is not interpretable by a human without post-hoc tooling."
        ),
    ),
    # A paper that states nothing must not appear in the table.
    Extraction(
        paper_id="p5",
        paper_hash="h5",
        summary="Spectral methods for node classification.",
        stated_limitation="",
    ),
]


@pytest.fixture
def graph():
    g, _, _ = build_graph(PAPERS, CONCEPTS, RELATIONS)
    return g


@pytest.fixture
def by_id():
    return {p.id: p for p in PAPERS}


# -- 1. the per-paper table ----------------------------------------------------


def test_only_papers_stating_a_limitation_appear(by_id):
    rows = paper_table(EXTRACTIONS, by_id)
    assert [r.paper_id for r in rows] == ["p4", "p3", "p2", "p1"]


def test_a_paper_stating_nothing_is_absent_not_blank(by_id):
    rows = paper_table(EXTRACTIONS, by_id)
    assert all(r.limitation for r in rows)
    assert "p5" not in {r.paper_id for r in rows}


def test_rows_are_newest_first_and_carry_labels(by_id):
    rows = paper_table(EXTRACTIONS, by_id)
    years = [r.year for r in rows]
    assert years == sorted(years, reverse=True)
    assert [r.label for r in rows] == ["L1", "L2", "L3", "L4"]


def test_the_table_renders_with_a_citation_per_row(by_id):
    table = render_table(paper_table(EXTRACTIONS, by_id))
    assert "| [L1] |" in table
    assert table.count("| [L") == 4


def test_an_empty_table_says_so_rather_than_looking_broken():
    assert "No paper" in render_table([])


def test_a_missing_paper_still_yields_a_row():
    """An extraction whose paper is not in the corpus must not crash the report."""
    rows = paper_table([EXTRACTIONS[0]], {})
    assert rows[0].title == EXTRACTIONS[0].paper_id


def test_a_long_limitation_cannot_break_the_table(by_id):
    long = Extraction(
        paper_id="p1", paper_hash="x", summary="s",
        stated_limitation="word " * 300,
    )
    table = render_table(paper_table([long], by_id))
    for line in table.splitlines():
        assert line.count("|") == 5


# -- 2. theme clustering -------------------------------------------------------


def test_each_limitation_lands_in_exactly_one_theme(by_id):
    rows = paper_table(EXTRACTIONS, by_id)
    themes = cluster_themes(rows)
    assert sum(t.count for t in themes) == len(rows)


def test_a_scaling_limitation_is_classified_as_scalability():
    assert classify_theme("It does not scale to millions of edges.") == "scalability"


def test_a_convergence_limitation_is_robustness_not_theory():
    assert classify_theme("No convergence guarantee in adversarial settings.") == "robustness"


def test_an_unmatched_limitation_falls_into_other():
    assert classify_theme("The paper is 12 pages long.") == "other"


def test_themes_are_ordered_by_how_often_they_occur(by_id):
    themes = cluster_themes(paper_table(EXTRACTIONS, by_id))
    counts = [t.count for t in themes]
    assert counts == sorted(counts, reverse=True)


def test_theme_labels_carry_the_underlying_rows(by_id):
    """Two papers complaining about scale become one gap citing both rows."""
    themes = cluster_themes(paper_table(EXTRACTIONS, by_id))
    scalability = next(t for t in themes if t.name == "scalability")
    assert scalability.count == 2
    assert scalability.labels == ["L3", "L4"]


# -- 3. structural gaps --------------------------------------------------------


def test_an_old_unfollowed_concept_is_a_structural_gap(graph):
    gaps = structural_gaps(graph)
    names = {g.name for g in gaps}
    assert "spectral graph methods" in names


def test_a_concept_at_the_corpus_edge_is_not_a_structural_gap(graph):
    """`graph diffusion models` is 2025, the corpus's newest year, so it has had
    no chance to be built on. Silence about it proves nothing."""
    assert "graph diffusion models" not in {g.name for g in structural_gaps(graph)}


def test_oldness_is_measured_against_the_corpus_not_the_calendar(graph):
    """`graph RL policies` (2022) is flagged even though 2022 is recent in
    absolute terms: the corpus runs to 2025, so it has had three years."""
    assert "graph RL policies" in {g.name for g in structural_gaps(graph)}


def test_a_corpus_of_only_recent_papers_still_finds_gaps():
    """A 2022-2025 corpus must not report zero structural gaps by default."""
    years = [2022, 2023, 2024, 2025]
    papers = [Paper(id=f"r{i}", title=f"R{i}", year=y) for i, y in enumerate(years)]
    concepts = [
        Concept(id="c:old", name="abandoned direction", first_seen_year=2022),
        Concept(id="c:new", name="current direction", first_seen_year=2025),
    ]
    g, _, _ = build_graph(
        papers,
        concepts,
        [
            Relation(source_id="r0", target_id="c:old", edge_type=EdgeType.INTRODUCES),
            Relation(source_id="r3", target_id="c:new", edge_type=EdgeType.INTRODUCES),
        ],
    )
    names = {x.name for x in structural_gaps(g)}
    assert "abandoned direction" in names
    assert "current direction" not in names


def test_raising_the_age_threshold_shrinks_the_gap_set(graph):
    """The threshold is a real dial: a stricter reading of "old" finds fewer."""
    generous = {g.name for g in structural_gaps(graph, min_age=0)}
    strict = {g.name for g in structural_gaps(graph, min_age=4)}
    assert strict < generous
    assert "spectral graph methods" in strict
    assert "graph RL policies" not in strict


def test_a_concept_with_in_degree_is_not_a_structural_gap(graph):
    """GAT is old, but `attention -> gat` gives it an in-edge, so it is not flagged.

    The spec's rule is in-degree ("few EXTENDS edges pointing to them"), which is
    what traverse.py's structural-gap heuristic already uses, so both stages
    agree on what counts as abandoned.
    """
    assert "graph attention networks" not in {g.name for g in structural_gaps(graph)}


def test_a_concept_nothing_touches_is_a_structural_gap(graph):
    """c:scale is 2019, old enough to judge, and has no lineage edges at all."""
    assert "sparse attention scaling" in {g.name for g in structural_gaps(graph)}


def test_a_structural_gap_names_the_papers_that_introduce_it(graph):
    gap = next(g for g in structural_gaps(graph) if g.name == "spectral graph methods")
    assert gap.papers == ["p5"]
    assert "no concept in the corpus extends" in gap.reason


def test_structural_gaps_are_labelled_and_newest_first(graph):
    gaps = structural_gaps(graph)
    assert [g.label for g in gaps] == [f"S{i}" for i in range(1, len(gaps) + 1)]


def test_papers_are_never_structural_gaps(graph):
    gaps = structural_gaps(graph)
    assert all(graph.nodes[g.concept_id]["type"] == str(NodeType.CONCEPT) for g in gaps)


def test_an_extends_edge_from_a_paper_does_not_count_as_a_successor(graph):
    """Only concept-to-concept lineage suppresses a structural gap."""
    gap = next(g for g in structural_gaps(graph) if g.name == "spectral graph methods")
    assert gap.in_degree == 0


# -- 4. ranking ----------------------------------------------------------------


def test_ranking_is_sorted_by_descending_score(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    scores = [g.score for g in report.ranked]
    assert scores == sorted(scores, reverse=True)


def test_both_kinds_of_gap_survive_into_the_ranking(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    kinds = {g.kind for g in report.ranked}
    assert kinds == {"stated", "structural"}


def test_a_repeated_theme_outranks_a_single_one(graph):
    rows = paper_table(EXTRACTIONS, {p.id: p for p in PAPERS})
    themes = cluster_themes(rows)
    ranked = rank_gaps(themes, structural_gaps(graph))
    stated = [g for g in ranked if g.kind == "stated"]
    assert stated[0].score >= stated[-1].score


def test_every_ranked_gap_carries_a_citation(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    for gap in report.ranked:
        assert gap.citations, f"{gap.key} has no citation"


def test_repetition_saturates_rather_than_growing_forever():
    """Many papers agreeing is evidence, not a reason to rank above everything."""
    rows = paper_table(EXTRACTIONS * 10, {p.id: p for p in PAPERS})
    ranked = rank_gaps(cluster_themes(rows), [])
    worst = max(g.score for g in ranked)
    assert worst < 6.0


# -- 5. suppression ------------------------------------------------------------


def test_a_gap_closed_by_a_newer_paper_is_suppressed():
    extractions = [
        Extraction(
            paper_id="p1", paper_hash="h1",
            summary="Dense attention for graphs.",
            stated_limitation="Memory cost prevents use on graphs with millions of edges.",
        ),
        Extraction(
            paper_id="p2", paper_hash="h2",
            summary=(
                "We address the memory cost of dense attention by learning sparse "
                "attention patterns, which scales to millions of edges."
            ),
            stated_limitation="Sparse patterns are chosen heuristically.",
        ),
    ]
    papers = {
        "p1": Paper(id="p1", title="Dense GAT", year=2018),
        "p2": Paper(id="p2", title="Sparse GAT", year=2021),
    }
    report = build_gap_report(extractions, None, list(papers.values()))
    assert report.closed, "the scaling gap should be recognised as addressed"
    assert any("scalability" in g.key or "scal" in g.title for g in report.closed)


def test_a_paper_mentioning_a_theme_does_not_close_its_gap():
    """A shared word is not evidence of an answer; an explicit marker is."""
    extractions = [
        Extraction(
            paper_id="p1", paper_hash="h1",
            summary="Attention over graphs.",
            stated_limitation="Memory cost prevents use at scale.",
        ),
        Extraction(
            paper_id="p2", paper_hash="h2",
            summary="We also consider memory. Attention on larger graphs is studied.",
            stated_limitation="",
        ),
    ]
    papers = {
        "p1": Paper(id="p1", title="A", year=2018),
        "p2": Paper(id="p2", title="B", year=2021),
    }
    report = build_gap_report(extractions, None, list(papers.values()))
    assert not report.closed


def test_an_older_paper_cannot_close_a_newer_gap():
    extractions = [
        Extraction(
            paper_id="p1", paper_hash="h1", summary="Early work.",
            stated_limitation="Memory cost prevents use at scale on dense graphs.",
        ),
        Extraction(
            paper_id="p2", paper_hash="h2",
            summary="We address the memory cost of dense attention patterns at scale.",
            stated_limitation="",
        ),
    ]
    papers = {
        "p1": Paper(id="p1", title="Newer", year=2023),
        "p2": Paper(id="p2", title="Older", year=2018),
    }
    report = build_gap_report(extractions, None, list(papers.values()))
    assert not report.closed, "only a strictly newer paper can close a gap"


def test_suppression_returns_both_kept_and_closed():
    ranked = [RankedGap(key="k", kind="stated", title="t", score=1.0, citations=["L1"])]
    keep, closed = suppress_closed(ranked, [], {})
    assert keep == ranked
    assert closed == []


def test_a_mention_never_closes_a_structural_gap(graph):
    """Structural gaps are graph evidence; a title match is not lineage.

    `spectral graph methods` has no EXTENDS in-edge, and a later paper whose
    title contains the same words must not make it look resolved.
    """
    extractions = [
        Extraction(
            paper_id="p2", paper_hash="h2",
            summary=(
                "We address the spectral graph methods setting for grid control, "
                "revisiting that abandoned line of work."
            ),
            stated_limitation="",
        )
    ]
    papers = {
        "p2": Paper(id="p2", title="Spectral Graph Methods for Grid Control", year=2025),
    }
    report = build_gap_report(extractions, graph, list(papers.values()))
    names = {g.title for g in report.ranked if g.kind == "structural"}
    assert "spectral graph methods" in names
    assert not [g for g in report.closed if g.kind == "structural"]


# -- the report ----------------------------------------------------------------


def test_the_report_has_both_required_sections(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    text = render_report(report)
    assert "## Per-paper stated limitations" in text
    assert "## Synthesised gaps, ranked" in text


def test_every_claim_in_the_ranked_section_carries_a_citation(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    text = render_report(report)
    section = text.split("## Synthesised gaps, ranked")[1]
    numbered = [
        line for line in section.splitlines()
        if line.strip() and line[0].isdigit() and "**" in line
    ]
    assert numbered
    for line in numbered:
        assert "[" in line and "]" in line, f"uncited claim: {line}"


def test_the_report_states_how_much_was_analysed(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    assert "5 paper(s) analysed" in render_report(report)
    assert "4 state a limitation" in render_report(report)


def test_a_corpus_with_nothing_stated_still_reports_structural_gaps(graph):
    """An empty extraction set must not erase what the graph alone shows."""
    report = build_gap_report([], graph, [])
    assert report.papers_with_limitations == 0
    assert report.ranked
    assert all(g.kind == "structural" for g in report.ranked)


def test_an_empty_corpus_with_no_graph_produces_an_honest_report():
    report = build_gap_report([], None, [])
    text = render_report(report)
    assert "No gap could be grounded" in text
    assert "0 paper(s) analysed" in text


def test_the_citation_index_resolves_every_emitted_label(graph):
    report = build_gap_report(EXTRACTIONS, graph, PAPERS)
    index = report.citation_index()
    emitted = {c for g in report.ranked for c in g.citations}
    assert emitted
    for label in emitted:
        assert index.get(label), f"label {label} has no resolvable meaning"


def test_building_a_report_without_a_graph_still_works():
    """Stated gaps must not depend on the graph being present."""
    report = build_gap_report(EXTRACTIONS, None, PAPERS)
    assert report.rows
    assert all(g.kind == "stated" for g in report.ranked)
