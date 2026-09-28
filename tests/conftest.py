from __future__ import annotations

import pytest

from rla.config import Settings
from rla.models import Concept, EdgeType, Paper, Relation, RelationType
from rla.store.cache import Cache
from rla.store.graph_store import build_graph


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        gemini_api_key="test-key",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        # Tests must not wait out the real Semantic Scholar throttle.
        s2_delay_seconds=0.0,
        max_retries=1,
    )


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(tmp_path / "cache.db")


@pytest.fixture
def papers() -> list[Paper]:
    return [
        Paper(id="p1", title="Graph Attention Networks", year=2018, doi="10.5555/3327757.3327764"),
        Paper(
            id="p2", title="Graph-of-Agents", year=2024, doi="10.5555/9999999.1", references=["p1"]
        ),
        Paper(id="p3", title="MAGMA", year=2024, doi="10.5555/9999999.2"),
    ]


@pytest.fixture
def graph_and_papers(papers):
    concepts = [
        Concept(id="c:gat", name="graph attention networks", first_seen_year=2018),
        Concept(id="c:agent-graphs", name="agent graphs", first_seen_year=2024),
    ]
    relations = [
        Relation(
            source_id="c:gat",
            target_id="c:agent-graphs",
            edge_type=EdgeType.EXTENDS,
            relation=RelationType.EXTENDS,
        ),
        Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES),
    ]
    graph, report = build_graph(papers, concepts, relations)
    return graph, papers, report
