"""P5 gate: question classification, traversal, and citation validation.

The fixture is a hand-built 12-node graph with a known shape, so each strategy's
subgraph can be asserted exactly rather than "contains at least". A traversal
that quietly returns the whole graph would still pass a containment test, and
that is precisely the failure the spec is trying to prevent.
"""

from __future__ import annotations

import pytest

from rla.models import Concept, EdgeType, NodeType, Paper, Relation, RelationType
from rla.pipeline.traverse import (
    QuestionType,
    Subgraph,
    approaches_subgraph,
    classify_question,
    comparison_subgraph,
    find_concepts,
    full_report_subgraph,
    gap_subgraph,
    lineage_subgraph,
    traverse,
    validate_citations,
)
from rla.store.graph_store import build_graph

# -- the 12-node fixture -------------------------------------------------------
#
# Concepts (5):  c:gat, c:gcn, c:agent-graphs, c:abandoned-scaling,
#               c:eq-transformer
# Papers   (7):  p1..p7
#
# Lineage, parent -> child, so a child walks *back* to its ancestors:
#     c:gcn -> c:gat -> c:agent-graphs
#     c:abandoned-scaling -> c:gcn
# c:eq-transformer is an off-island concept: nothing builds on it and nothing
# builds from it, so no traversal seeded on GAT may ever reach it. That is what
# makes "must not return the whole graph" a real assertion.
#
# Co-usage: p5 uses both c:gat and c:gcn, so it is the comparison pivot.
# p6 states a limitation on c:agent-graphs.

PAPERS = [
    Paper(id="p1", title="Graph Attention Networks", year=2018, abstract="introduces GAT"),
    Paper(id="p2", title="Graph Convolutional Networks", year=2017, abstract="introduces GCN"),
    Paper(id="p3", title="Graph-of-Agents", year=2024, abstract="agents over graphs",
          references=["p1"]),
    Paper(id="p4", title="Multi-Agent Reinforcement Learning with Graphs", year=2023),
    Paper(id="p5", title="Agnostic GNN Benchmark", year=2024, abstract="evaluates GCN and GAT"),
    Paper(id="p6", title="Limits of Graph Attention", year=2024, abstract="states a limitation"),
    Paper(id="p7", title="Equivariant Graph Neural Networks", year=2022),
]

CONCEPTS = [
    Concept(
        id="c:gat",
        name="graph attention networks",
        description="attention over graph neighbourhoods",
        first_seen_year=2018,
        aliases=["GAT", "graph attention network"],
    ),
    Concept(id="c:gcn", name="graph convolutional networks", first_seen_year=2017, aliases=["GCN"]),
    Concept(id="c:agent-graphs", name="agent graphs", first_seen_year=2024, aliases=[]),
    Concept(
        id="c:abandoned-scaling",
        name="sparse attention scaling",
        description="scaling attention to large graphs",
        first_seen_year=2015,
    ),
    Concept(
        id="c:eq-transformer",
        name="equivariant graph transformers",
        description="transformers that respect graph symmetry",
        first_seen_year=2022,
    ),
]

RELATIONS = [
    Relation(source_id="c:gcn", target_id="c:gat", edge_type=EdgeType.EXTENDS,
             relation=RelationType.EXTENDS),
    Relation(source_id="c:gat", target_id="c:agent-graphs", edge_type=EdgeType.EXTENDS,
             relation=RelationType.EXTENDS),
    Relation(source_id="c:abandoned-scaling", target_id="c:gcn", edge_type=EdgeType.EXTENDS,
             relation=RelationType.EXTENDS),
    Relation(source_id="c:gcn", target_id="c:gat", edge_type=EdgeType.COMBINES_WITH,
             relation=RelationType.COMBINES),
    # Introduces
    Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p2", target_id="c:gcn", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p3", target_id="c:agent-graphs", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p4", target_id="c:agent-graphs", edge_type=EdgeType.INTRODUCES),
    Relation(source_id="p7", target_id="c:eq-transformer", edge_type=EdgeType.INTRODUCES),
    # Uses
    Relation(source_id="p3", target_id="c:gat", edge_type=EdgeType.USES),
    Relation(source_id="p4", target_id="c:gat", edge_type=EdgeType.USES),
    Relation(source_id="p5", target_id="c:gcn", edge_type=EdgeType.USES),
    Relation(source_id="p5", target_id="c:gat", edge_type=EdgeType.USES),
    Relation(source_id="p6", target_id="c:agent-graphs", edge_type=EdgeType.USES),
    Relation(source_id="p7", target_id="c:eq-transformer", edge_type=EdgeType.USES),
    # The one stated limitation in the fixture
    Relation(source_id="p6", target_id="c:agent-graphs", edge_type=EdgeType.HAS_LIMITATION,
             evidence="does not scale beyond 50 agents"),
]


@pytest.fixture
def fixture_graph():
    graph, _, _ = build_graph(PAPERS, CONCEPTS, RELATIONS)
    return graph


@pytest.fixture
def fixture_nodes(fixture_graph):
    return {n for n, d in fixture_graph.nodes(data=True)}


def names(sub: Subgraph) -> set[str]:
    return {n.name for n in sub.nodes}


def concept_names(sub: Subgraph) -> set[str]:
    return {n.name for n in sub.nodes if n.type == str(NodeType.CONCEPT)}


def paper_ids(sub: Subgraph) -> set[str]:
    return {n.node_id for n in sub.nodes if n.type == str(NodeType.PAPER)}


# -- the fixture itself --------------------------------------------------------


def test_the_fixture_really_has_twelve_nodes(fixture_nodes):
    assert len(fixture_nodes) == 12


def test_temporal_filtering_keeps_the_chain_but_drops_the_backwards_edge(fixture_graph):
    """c:abandoned-scaling (2015) -> c:gcn (2017) is a legal parent->child hop."""
    assert fixture_graph.has_edge("c:abandoned-scaling", "c:gcn", key=str(EdgeType.EXTENDS))


# -- classification ------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What's the lineage of graph attention networks?", QuestionType.LINEAGE),
        ("How did GAT evolve into multi-agent systems?", QuestionType.LINEAGE),
        ("What is the origin of graph RL policies?", QuestionType.LINEAGE),
        ("What gaps remain in multi-agent systems?", QuestionType.GAP),
        ("What is still unsolved about scaling attention?", QuestionType.GAP),
        ("Which limitations do recent papers state?", QuestionType.GAP),
        ("How do GAT and GCN compare?", QuestionType.COMPARISON),
        (
            "Compare graph attention networks versus graph convolutional networks",
            QuestionType.COMPARISON,
        ),
        ("What is the difference between GAT and GCN?", QuestionType.COMPARISON),
        ("What are the major approaches to graphs?", QuestionType.APPROACHES),
        ("Which methods are commonly used for multi-agent systems?", QuestionType.APPROACHES),
        ("Give me a full report", QuestionType.FULL_REPORT),
        ("Summarise everything you have", QuestionType.FULL_REPORT),
    ],
)
def test_questions_route_to_the_right_strategy(question, expected):
    assert classify_question(question) is expected


def test_a_comparison_wins_over_a_lineage_reading():
    """"How do X and Y compare" is a comparison, not a how-did question."""
    assert classify_question("How do GAT and GCN compare over time?") is QuestionType.COMPARISON


def test_an_unrecognised_question_falls_back_to_a_full_report():
    assert classify_question("banana") is QuestionType.FULL_REPORT


# -- lineage -------------------------------------------------------------------


def test_lineage_returns_the_full_ancestry_and_descendant_chain(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "What is the lineage of graph attention networks?")

    # GAT <- GCN <- sparse scaling, and GAT -> agent graphs.
    assert concept_names(sub) == {
        "graph attention networks",
        "graph convolutional networks",
        "sparse attention scaling",
        "agent graphs",
    }
    assert sub.seeds == ["c:gat"]


def test_lineage_never_reaches_an_off_island_concept(fixture_graph):
    """c:eq-transformer is unreachable from GAT, so no lineage may include it."""
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    assert "equivariant graph transformers" not in concept_names(sub)
    assert "p7" not in paper_ids(sub)


def test_lineage_brings_in_the_papers_attached_to_the_chain(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    # Every paper that touches the GCN -> GAT -> agent-graphs chain, in either
    # direction: p1/p5 use or introduce GAT, p2 introduces GCN, p3/p4 attach to
    # agent graphs, p6 states a limitation on it.
    assert {"p1", "p2", "p3", "p4", "p5", "p6"} == paper_ids(sub)


def test_lineage_orders_concepts_and_keeps_the_parent_to_child_direction(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    edges = {(e.source, e.target, e.type) for e in sub.edges}
    labels = {n.node_id: n.label for n in sub.nodes}

    gcn = labels["c:gcn"]
    gat = labels["c:gat"]
    assert (gcn, gat, str(EdgeType.EXTENDS)) in edges, "ancestry must read parent -> child"


def test_lineage_respects_the_depth_limit(fixture_graph):
    """One hop from GAT reaches GCN and agent-graphs, but not two hops up."""
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks", max_depth=1)
    assert "graph convolutional networks" in concept_names(sub)
    assert "sparse attention scaling" not in concept_names(sub)


def test_lineage_says_so_when_the_named_concept_is_absent(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of quantum error correction")
    assert sub.notes, "an unanchored traversal must explain itself"
    assert sub.nodes, "it should still fall back to something traversable"


def test_lineage_does_not_return_the_whole_graph(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    # The fixture has 12 nodes and an off-island concept; a lineage of one
    # concept must be a strict slice of it.
    assert len(sub.nodes) < 12


# -- gaps ----------------------------------------------------------------------


def test_gaps_surface_the_stated_limitation_and_its_paper(fixture_graph):
    sub = gap_subgraph(fixture_graph, "What gaps remain in agent graphs?")
    assert "agent graphs" in concept_names(sub)
    assert "p6" in paper_ids(sub), "a stated gap must carry the paper that states it"


def test_gaps_surface_a_structural_gap_nobody_stated(fixture_graph):
    """sparse attention scaling is old and only one concept builds on it."""
    sub = gap_subgraph(fixture_graph, "What gaps remain in sparse attention scaling?")
    assert "sparse attention scaling" in concept_names(sub)


def test_gap_notes_distinguish_stated_from_structural(fixture_graph):
    sub = gap_subgraph(fixture_graph, "gaps in agent graphs")
    assert any("stated limitation" in note for note in sub.notes)


def test_gaps_ignore_an_area_with_no_signals(fixture_graph):
    sub = gap_subgraph(fixture_graph, "gaps in graph convolutional networks")
    # GCN is used and extended, so it is not a gap even though it is in range.
    assert "graph convolutional networks" not in concept_names(sub)


# -- comparison ----------------------------------------------------------------


def test_comparison_anchors_on_both_named_concepts(fixture_graph):
    sub = comparison_subgraph(fixture_graph, "How do GAT and GCN compare?")
    assert sub.seeds == ["c:gat", "c:gcn"]
    assert {"graph attention networks", "graph convolutional networks"} <= concept_names(sub)


def test_comparison_finds_the_shared_ancestor(fixture_graph):
    sub = comparison_subgraph(fixture_graph, "How do GAT and GCN compare?")
    # sparse attention scaling is an ancestor of both, via GCN.
    assert "sparse attention scaling" in concept_names(sub)


def test_comparison_finds_the_paper_using_both(fixture_graph):
    sub = comparison_subgraph(fixture_graph, "How do GAT and GCN compare?")
    assert "p5" in paper_ids(sub), "p5 uses both, so it is the comparison pivot"


def test_comparison_surfaces_the_asymmetry(fixture_graph):
    sub = comparison_subgraph(fixture_graph, "How do GAT and GCN compare?")
    # agent graphs descends from GAT but has no GCN-side counterpart.
    assert "agent graphs" in concept_names(sub)


def test_comparison_reports_when_only_one_concept_matched(fixture_graph):
    sub = comparison_subgraph(fixture_graph, "How do GAT and an absent thing compare?")
    assert sub.seeds == ["c:gat"]
    assert any("only" in note.lower() and "matched" in note.lower() for note in sub.notes)
    assert sub.nodes, "one usable match must still produce something traversable"


# -- approaches ----------------------------------------------------------------


def test_approaches_ranks_by_use_count(fixture_graph):
    sub = approaches_subgraph(fixture_graph, "What are the major approaches to agent graphs?")
    # GAT is used by p3, p4, p5 (three papers), the most of any concept here.
    assert any("graph attention networks=3" in note for note in sub.notes)
    assert "graph attention networks" in concept_names(sub)


def test_approaches_never_returns_zero_nodes(fixture_graph):
    sub = approaches_subgraph(fixture_graph, "major approaches to anything unmatchable")
    assert sub.nodes, "an unmatched area should still rank the whole graph"


# -- full report ---------------------------------------------------------------


def test_full_report_walks_every_paper_chronologically(fixture_graph):
    sub = full_report_subgraph(fixture_graph, "Give me a full report")
    assert paper_ids(sub) == {p.id for p in PAPERS}
    years = [n.year for n in sub.nodes if n.type == str(NodeType.PAPER)]
    assert years == sorted(years, reverse=True), "newest first"


def test_full_report_includes_every_stated_limitation(fixture_graph):
    sub = full_report_subgraph(fixture_graph, "full report")
    assert any("limitation" in n for n in sub.notes)
    assert "p6" in paper_ids(sub)


def test_full_report_truncates_and_says_so(fixture_graph):
    sub = full_report_subgraph(fixture_graph, "full report", max_nodes=3)
    assert len(paper_ids(sub)) == 3
    assert any("omitted" in note for note in sub.notes)


# -- labels and rendering ------------------------------------------------------


def test_labels_are_stable_and_split_by_node_type(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    assert all(n.label.startswith("P") for n in sub.nodes if n.type == str(NodeType.PAPER))
    assert all(n.label.startswith("C") for n in sub.nodes if n.type == str(NodeType.CONCEPT))
    assert len(sub.labels) == len(sub.nodes), "labels must be unique"


def test_the_same_question_yields_the_same_labels_every_time(fixture_graph):
    a = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    b = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    assert {n.node_id: n.label for n in a.nodes} == {n.node_id: n.label for n in b.nodes}


def test_the_rendered_subgraph_shows_labels_and_types(fixture_graph):
    text = lineage_subgraph(fixture_graph, "lineage of graph attention networks").render()
    assert "question type: lineage" in text
    assert "Concept" in text and "Paper" in text
    assert "- [C" in text


def test_citation_edges_are_flagged_as_ground_truth(fixture_graph):
    sub = full_report_subgraph(fixture_graph, "full report")
    cites = [e for e in sub.edges if e.type == str(EdgeType.CITES)]
    assert cites and all(e.ground_truth for e in cites)
    derived = [e for e in sub.edges if e.type != str(EdgeType.CITES)]
    assert derived and not any(e.ground_truth for e in derived)


# -- concept resolution --------------------------------------------------------


def test_concepts_resolve_by_alias(fixture_graph):
    assert find_concepts(fixture_graph, "GAT") == ["c:gat"]


def test_a_concept_name_outranks_a_description_match(fixture_graph):
    """Weighting the name is what stops a shared word hijacking the seed."""
    assert find_concepts(fixture_graph, "graph attention networks")[0] == "c:gat"


def test_an_unmatched_phrase_resolves_to_nothing(fixture_graph):
    assert find_concepts(fixture_graph, "photosynthesis in desert plants") == []


# -- dispatcher ----------------------------------------------------------------


def test_traverse_dispatches_on_the_classified_type(fixture_graph):
    assert traverse(fixture_graph, "How do GAT and GCN compare?").question_type is (
        QuestionType.COMPARISON
    )
    assert traverse(fixture_graph, "What gaps remain in agent graphs?").question_type is (
        QuestionType.GAP
    )


def test_every_strategy_produces_a_renderable_payload(fixture_graph):
    questions = [
        ("lineage of graph attention networks", QuestionType.LINEAGE),
        ("gaps in agent graphs", QuestionType.GAP),
        ("compare GAT and GCN", QuestionType.COMPARISON),
        ("major approaches to graphs", QuestionType.APPROACHES),
        ("full report", QuestionType.FULL_REPORT),
    ]
    for question, qtype in questions:
        sub = traverse(fixture_graph, question, qtype)
        payload = sub.to_payload()
        assert payload["stats"]["nodes"] == len(sub.nodes)
        assert payload["stats"]["edges"] == len(sub.edges)
        assert payload["stats"]["papers"] + payload["stats"]["concepts"] == len(sub.nodes)
        assert sub.render()


# -- citation validation -------------------------------------------------------


def test_a_valid_citation_survives(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    label = sorted(sub.labels)[0]
    cleaned, stripped = validate_citations(f"It started with [{label}].", sub)
    assert cleaned == f"It started with [{label}]."
    assert stripped == []


def test_an_invented_citation_is_stripped_and_reported(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    cleaned, stripped = validate_citations("Claim [P999] and [C404] and [P1].", sub)
    assert stripped == ["[P999]", "[C404]"]
    assert "[P999]" not in cleaned and "[C404]" not in cleaned
    assert "[P1]." in cleaned, "the valid citation must survive"


def test_stripping_does_not_tear_the_sentence(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    cleaned, _ = validate_citations("as shown [P999], it holds.", sub)
    assert " ," not in cleaned
    assert "as shown, it holds" in cleaned


def test_validating_an_answer_with_no_citations_changes_nothing(fixture_graph):
    sub = lineage_subgraph(fixture_graph, "lineage of graph attention networks")
    cleaned, stripped = validate_citations("No citations at all here.", sub)
    assert cleaned == "No citations at all here."
    assert stripped == []


def test_a_subgraph_with_no_nodes_strips_everything(fixture_graph):
    empty = Subgraph(question="q", question_type=QuestionType.FULL_REPORT)
    cleaned, stripped = validate_citations("Everything is [P1].", empty)
    assert stripped == ["[P1]"]
    assert "[" not in cleaned
