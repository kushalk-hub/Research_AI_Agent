"""NetworkX graph construction, persistence, and temporal-constraint cleaning.

Neo4j is unavailable on this machine (no Docker), so NetworkX is the primary
store per spec section 3c. Graphs here are 40-100 papers / tens of concepts,
well within NetworkX's comfortable range. Export targets (`graphml`, D3 JSON)
keep a later migration to Neo4j or a browser view cheap.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import networkx as nx

from rla.models import Concept, EdgeType, NodeType, Paper, Relation

Graph = nx.MultiDiGraph

#: Edge types that assert a temporal ordering: child must be strictly newer.
TEMPORAL_EDGES: frozenset[EdgeType] = frozenset({EdgeType.EXTENDS, EdgeType.REPLACES})


def empty_graph() -> Graph:
    return nx.MultiDiGraph()


def year_of(graph: Graph, node_id: str) -> int | None:
    return graph.nodes[node_id].get("year") or graph.nodes[node_id].get("first_seen_year")


def add_papers(graph: Graph, papers: Iterable[Paper]) -> None:
    for paper in papers:
        if graph.has_node(paper.id):
            continue
        attrs = paper.model_dump()
        attrs.update(type=str(NodeType.PAPER), label=paper.title, year=paper.year)
        graph.add_node(paper.id, **attrs)


def add_concepts(graph: Graph, concepts: Iterable[Concept]) -> None:
    for concept in concepts:
        if graph.has_node(concept.id):
            continue
        attrs = concept.model_dump()
        attrs.update(type=str(NodeType.CONCEPT), label=concept.name, year=concept.first_seen_year)
        graph.add_node(concept.id, **attrs)


def add_citation_edges(graph: Graph, papers: Iterable[Paper]) -> int:
    """`Paper --CITES--> Paper` straight from citation ground truth, no LLM involved."""
    known = {p.id for p in papers}
    added = 0
    for paper in papers:
        for cited in paper.references:
            if cited in known and not graph.has_edge(paper.id, cited, key=str(EdgeType.CITES)):
                graph.add_edge(
                    paper.id,
                    cited,
                    key=str(EdgeType.CITES),
                    type=str(EdgeType.CITES),
                    ground_truth=True,
                )
                added += 1
        for citing in paper.citations:
            if citing in known and not graph.has_edge(citing, paper.id, key=str(EdgeType.CITES)):
                graph.add_edge(
                    citing,
                    paper.id,
                    key=str(EdgeType.CITES),
                    type=str(EdgeType.CITES),
                    ground_truth=True,
                )
                added += 1
    return added


def add_relations(graph: Graph, relations: Iterable[Relation]) -> int:
    """Add LLM-derived edges, skipping any endpoint that is not in the graph."""
    added = 0
    for relation in relations:
        if not (graph.has_node(relation.source_id) and graph.has_node(relation.target_id)):
            continue
        if graph.has_edge(relation.source_id, relation.target_id, key=str(relation.edge_type)):
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
        added += 1
    return added


def enforce_temporal_constraints(graph: Graph) -> list[tuple[str, str, EdgeType]]:
    """A paper cannot extend a concept that did not exist yet (spec section 9).

    Drops any Concept--EXTENDS/REPLACES-->Concept edge where the child's year is
    not strictly greater than the parent's. Returns the dropped edges so the run
    can report them instead of silently mutating the graph.
    """
    dropped: list[tuple[str, str, EdgeType]] = []
    to_remove: list[tuple[str, str, str]] = []

    for source, target, key, data in graph.edges(keys=True, data=True):
        edge_type = data.get("type")
        if edge_type not in {e.value for e in TEMPORAL_EDGES}:
            continue
        if graph.nodes[source].get("type") != str(NodeType.CONCEPT):
            continue
        if graph.nodes[target].get("type") != str(NodeType.CONCEPT):
            continue
        child_year = year_of(graph, target)
        parent_year = year_of(graph, source)
        if child_year is None or parent_year is None:
            continue
        if child_year <= parent_year:
            to_remove.append((source, target, key))
            dropped.append((source, target, EdgeType(edge_type)))

    for source, target, key in to_remove:
        graph.remove_edge(source, target, key=key)
    return dropped


def build_graph(
    papers: Iterable[Paper],
    concepts: Iterable[Concept],
    relations: Iterable[Relation],
) -> tuple[Graph, dict[str, Any]]:
    papers = list(papers)
    graph = empty_graph()
    add_papers(graph, papers)
    add_concepts(graph, concepts)
    citations = add_citation_edges(graph, papers)
    derived = add_relations(graph, relations)
    dropped = enforce_temporal_constraints(graph)
    return graph, {
        "citations": citations,
        "derived_edges": derived,
        "temporal_violations_dropped": len(dropped),
        "temporal_violations": [{"source": s, "target": t, "edge": str(e)} for s, t, e in dropped],
    }


def stats(graph: Graph) -> dict[str, int]:
    node_types: dict[str, int] = {}
    for _, data in graph.nodes(data=True):
        node_types[data.get("type", "unknown")] = node_types.get(data.get("type", "unknown"), 0) + 1
    edge_types: dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        edge_types[data.get("type", "unknown")] = edge_types.get(data.get("type", "unknown"), 0) + 1
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        **{f"nodes_{k}": v for k, v in node_types.items()},
        **{f"edges_{k}": v for k, v in edge_types.items()},
    }


def to_serialisable(graph: Graph) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": node_id, **{k: v for k, v in data.items()}}
            for node_id, data in graph.nodes(data=True)
        ],
        "links": [
            {
                "source": u,
                "target": v,
                "type": data.get("type"),
                **{k: val for k, val in data.items() if k != "type"},
            }
            for u, v, data in graph.edges(data=True)
        ],
    }


def _graphml_safe(value: Any) -> Any:
    """GraphML only stores scalars, so flatten containers to strings and drop None."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(v) for v in value)
    if isinstance(value, dict):
        return ";".join(f"{k}={v}" for k, v in value.items())
    return value


def save(graph: Graph, json_path: Path, graphml_path: Path | None = None) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(to_serialisable(graph), indent=2, ensure_ascii=False), "utf-8")
    if graphml_path is not None:
        graphml_path.parent.mkdir(parents=True, exist_ok=True)
        # GraphML has no native multigraph support, so collapse to a simple digraph.
        simple = nx.DiGraph()
        for node_id, data in graph.nodes(data=True):
            attrs = {k: _graphml_safe(v) for k, v in data.items() if v is not None}
            simple.add_node(node_id, **attrs)
        for u, v, data in graph.edges(data=True):
            simple.add_edge(u, v, **{k: _graphml_safe(val) for k, val in data.items()})
        nx.write_graphml(simple, graphml_path)


def load(json_path: Path) -> Graph:
    payload = json.loads(Path(json_path).read_text("utf-8"))
    graph = empty_graph()
    for node in payload["nodes"]:
        graph.add_node(node.pop("id"), **node)
    for link in payload["links"]:
        edge_type = link.pop("type", None)
        # Restore the edge key from the type, as `add_citation_edges` /
        # `add_relations` keyed it. Without this the multigraph reassigns
        # integer keys and `has_edge(u, v, key="CITES")` silently starts
        # returning False on a reloaded graph.
        if edge_type is not None:
            link["type"] = edge_type
            graph.add_edge(link.pop("source"), link.pop("target"), key=str(edge_type), **link)
        else:
            graph.add_edge(link.pop("source"), link.pop("target"), **link)
    return graph


def subgraph_payload(graph: Graph, nodes: Iterable[str]) -> dict[str, Any]:
    """Trim the graph to `nodes` plus every edge between them.

    This is what the TUI renders and what the answer LLM receives (spec section 2,
    layer 4: a small relevant subgraph, not the whole graph).
    """
    keep = [n for n in dict.fromkeys(nodes) if graph.has_node(n)]
    return to_serialisable(graph.subgraph(keep))
