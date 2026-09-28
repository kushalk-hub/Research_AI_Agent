"""P0 gate: graph build, temporal constraint, persistence round-trip."""

from __future__ import annotations

from rla.models import Concept, EdgeType, Paper, Relation, RelationType
from rla.store.graph_store import (
    build_graph,
    enforce_temporal_constraints,
    load,
    save,
    stats,
    subgraph_payload,
)


def test_node_and_edge_types_land_in_the_graph(papers):
    graph, _report = build_graph(
        papers,
        [Concept(id="c:gat", name="graph attention networks", first_seen_year=2018)],
        [Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES)],
    )
    assert graph.nodes["p1"]["type"] == "Paper"
    assert graph.nodes["c:gat"]["type"] == "Concept"
    assert graph.get_edge_data("p1", "c:gat", "INTRODUCES")["ground_truth"] is False


def test_citation_edges_come_from_ground_truth(papers):
    graph, report = build_graph(papers, [], [])
    assert graph.has_edge("p2", "p1", key="CITES")
    assert report["citations"] == 1
    assert graph.get_edge_data("p2", "p1", "CITES")["ground_truth"] is True


def test_citation_edges_skip_unknown_ids(papers):
    papers[0].references.append("p-does-not-exist")
    graph, _ = build_graph(papers, [], [])
    assert "p-does-not-exist" not in graph.nodes


def test_relations_with_unknown_endpoints_are_skipped(papers):
    graph, report = build_graph(
        papers,
        [],
        [Relation(source_id="p1", target_id="c:ghost", edge_type=EdgeType.USES)],
    )
    assert report["derived_edges"] == 0
    assert "c:ghost" not in graph.nodes


def test_duplicate_edges_are_not_repeated(papers):
    relation = Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.USES)
    graph, report = build_graph(papers, [Concept(id="c:gat", name="gat")], [relation, relation])
    assert report["derived_edges"] == 1
    assert stats(graph)["edges_USES"] == 1


def test_temporal_constraint_drops_backwards_edges(papers):
    """`A --EXTENDS--> B` means "B builds on A", so B must be strictly newer."""
    concepts = [
        Concept(id="c:old", name="old", first_seen_year=2020),
        Concept(id="c:new", name="new", first_seen_year=2015),
    ]
    relations = [
        Relation(
            source_id="c:old",
            target_id="c:new",
            edge_type=EdgeType.EXTENDS,
            relation=RelationType.EXTENDS,
        )
    ]
    graph, report = build_graph(papers, concepts, relations)
    assert report["temporal_violations_dropped"] == 1
    assert not graph.has_edge("c:old", "c:new", key="EXTENDS")


def test_temporal_constraint_allows_forward_edges(papers):
    concepts = [
        Concept(id="c:old", name="old", first_seen_year=2015),
        Concept(id="c:new", name="new", first_seen_year=2020),
    ]
    relations = [
        Relation(
            source_id="c:old",
            target_id="c:new",
            edge_type=EdgeType.EXTENDS,
            relation=RelationType.EXTENDS,
        )
    ]
    graph, report = build_graph(papers, concepts, relations)
    assert report["temporal_violations_dropped"] == 0
    assert graph.has_edge("c:old", "c:new", key="EXTENDS")


def test_temporal_constraint_drops_same_year_edges(papers):
    concepts = [
        Concept(id="c:a", name="a", first_seen_year=2020),
        Concept(id="c:b", name="b", first_seen_year=2020),
    ]
    graph, _ = build_graph(papers, concepts, [])
    graph.add_edge("c:a", "c:b", key="EXTENDS", type="EXTENDS")
    assert len(enforce_temporal_constraints(graph)) == 1
    assert not graph.has_edge("c:a", "c:b", key="EXTENDS")


def test_temporal_constraint_ignores_missing_years(papers):
    graph, _ = build_graph(
        papers,
        [Concept(id="c:a", name="a"), Concept(id="c:b", name="b")],
        [],
    )
    graph.add_edge("c:a", "c:b", key="EXTENDS", type="EXTENDS")
    assert enforce_temporal_constraints(graph) == []
    assert graph.has_edge("c:a", "c:b", key="EXTENDS")


def test_temporal_constraint_only_applies_to_concept_concept(papers):
    graph, _ = build_graph(papers, [Concept(id="c:gat", name="gat", first_seen_year=2030)], [])
    graph.add_edge("p1", "c:gat", key="REPLACES", type="REPLACES")
    assert enforce_temporal_constraints(graph) == []


def test_temporal_constraint_leaves_other_edge_types_alone(papers):
    graph, _ = build_graph(
        papers,
        [
            Concept(id="c:a", name="a", first_seen_year=2020),
            Concept(id="c:b", name="b", first_seen_year=2010),
        ],
        [],
    )
    graph.add_edge("c:a", "c:b", key="COMBINES_WITH", type="COMBINES_WITH")
    assert enforce_temporal_constraints(graph) == []
    assert graph.has_edge("c:a", "c:b", key="COMBINES_WITH")


def test_persistence_round_trip(tmp_path, graph_and_papers):
    graph, _, _ = graph_and_papers
    json_path, graphml_path = tmp_path / "graph.json", tmp_path / "graph.graphml"
    save(graph, json_path, graphml_path)

    reloaded = load(json_path)
    assert stats(reloaded) == stats(graph)
    assert json_path.exists() and graphml_path.exists()


def test_stats_counts_node_and_edge_types(graph_and_papers):
    graph, _, _ = graph_and_papers
    result = stats(graph)
    assert result["nodes_Paper"] == 3
    assert result["nodes_Concept"] == 2
    assert result["edges_CITES"] == 1
    assert result["edges_EXTENDS"] == 1


def test_temporal_violations_are_reported_not_silent(graph_and_papers):
    _, _, report = graph_and_papers
    assert report["temporal_violations_dropped"] == 0
    assert report["temporal_violations"] == []


def test_subgraph_payload_keeps_only_requested_nodes(graph_and_papers):
    graph, _, _ = graph_and_papers
    payload = subgraph_payload(graph, ["p2", "p1", "p1", "nope"])
    assert sorted(n["id"] for n in payload["nodes"]) == ["p1", "p2"]
    assert len(payload["links"]) == 1


def test_paper_nodes_carry_year_for_traversal():
    graph, _ = build_graph([Paper(id="p1", title="T", year=2018)], [], [])
    assert graph.nodes["p1"]["year"] == 2018


def test_graphml_export_flattens_list_attributes(tmp_path):
    paper = Paper(id="p1", title="T", year=2018, authors=["Ada"], sources=["openalex", "arxiv"])
    graph, _ = build_graph([paper], [], [])
    graphml_path = tmp_path / "graph.graphml"
    save(graph, tmp_path / "graph.json", graphml_path)
    text = graphml_path.read_text("utf-8")
    assert "openalex;arxiv" in text
