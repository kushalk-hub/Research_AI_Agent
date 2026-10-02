"""P4 gate: §5 schema conformance, zero temporal violations, lossless persistence."""

from __future__ import annotations

import networkx as nx

from rla.events import PIPELINE_PHASES as PHASE_ORDER
from rla.events import Phase
from rla.models import (
    Concept,
    ConceptMention,
    Corpus,
    EdgeType,
    Extraction,
    NodeType,
    Paper,
    RelationType,
)
from rla.pipeline.graph_build import (
    build_graph_stage,
    build_research_graph,
    collect_relations,
    name_index,
    resolve_name,
)
from rla.store.graph_store import enforce_temporal_constraints, load, stats

GAT = Concept(
    id="concept:gat",
    name="graph attention networks",
    description="attend over neighbours",
    first_seen_year=2018,
    aliases=["GAT", "graph attention network"],
)
ATTENTION = Concept(id="concept:attention", name="attention", first_seen_year=2015)
GCN = Concept(id="concept:gcn", name="graph convolutional networks", first_seen_year=2017)
CONCEPTS = [GAT, ATTENTION, GCN]


def paper(pid: str, year: int, **kw) -> Paper:
    return Paper(id=pid, title=f"Paper {pid}", year=year, abstract="text", **kw)


def extraction(
    pid: str,
    *,
    concepts: list[ConceptMention] | None = None,
    relation: RelationType | None = None,
    target: str = "",
    builds_on: list[str] | None = None,
) -> Extraction:
    return Extraction(
        paper_id=pid,
        paper_hash=f"hash-{pid}",
        summary="s",
        concepts=concepts if concepts is not None else [],
        relation=relation,
        relation_target=target,
        builds_on=builds_on or [],
    )


def extraction_for(p: Paper, **kw) -> Extraction:
    """An extraction whose hash matches the paper, as the real pipeline writes it.

    The graph stage gates on store-vs-corpus integrity, so stage tests must use
    consistent hashes; the fake `hash-{pid}` would read as superseded content.
    """
    e = extraction(p.id, **kw)
    e.paper_hash = p.ensure_hash()
    return e


# -- Name resolution ------------------------------------------------------------


def test_every_spelling_of_a_concept_resolves_to_its_node():
    index = name_index(CONCEPTS)
    assert resolve_name("graph attention networks", index) == GAT.id
    assert resolve_name("GAT", index) == GAT.id
    assert resolve_name("G.A.T.", index) == GAT.id
    assert resolve_name("Graph Attention Network", index) == GAT.id


def test_an_unrelated_name_does_not_resolve():
    assert resolve_name("reinforcement learning", name_index(CONCEPTS)) is None


# -- §5 edge mapping ------------------------------------------------------------


def test_roles_become_the_schema_edge_types():
    relations, unresolved = collect_relations(
        [
            extraction(
                "p1",
                concepts=[
                    ConceptMention(name="attention", role="introduces"),
                    ConceptMention(name="GAT", role="uses"),
                    ConceptMention(name="graph convolutional networks", role="limitation"),
                ],
            )
        ],
        CONCEPTS,
    )
    edges = {(r.source_id, r.target_id, str(r.edge_type)) for r in relations}
    assert edges == {
        ("p1", ATTENTION.id, "INTRODUCES"),
        ("p1", GAT.id, "USES"),
        ("p1", GCN.id, "HAS_LIMITATION"),
    }
    assert unresolved == []


def test_an_unrecognised_role_is_treated_as_the_weakest_claim():
    relations, _ = collect_relations(
        [extraction("p1", concepts=[ConceptMention(name="attention", role="puzzles")])], CONCEPTS
    )
    assert relations[0].edge_type is EdgeType.USES


def test_extends_points_from_the_older_concept_to_the_newer_one():
    """`A --EXTENDS--> B` means "B builds on A", so the child must be newer."""
    relations, _ = collect_relations(
        [
            extraction(
                "p1",
                concepts=[ConceptMention(name="graph attention networks", role="introduces")],
                relation=RelationType.EXTENDS,
                target="attention",
            )
        ],
        CONCEPTS,
    )
    lineage = [r for r in relations if r.edge_type is EdgeType.EXTENDS]
    assert len(lineage) == 1
    assert (lineage[0].source_id, lineage[0].target_id) == (ATTENTION.id, GAT.id)


def test_replaces_and_combines_follow_the_same_direction():
    for relation, edge in (
        (RelationType.REPLACES, EdgeType.REPLACES),
        (RelationType.COMBINES, EdgeType.COMBINES_WITH),
    ):
        relations, _ = collect_relations(
            [
                extraction(
                    "p1",
                    concepts=[ConceptMention(name="graph attention networks", role="introduces")],
                    relation=relation,
                    target="attention",
                )
            ],
            CONCEPTS,
        )
        edge_rel = [r for r in relations if r.edge_type is edge]
        assert len(edge_rel) == 1
        assert (edge_rel[0].source_id, edge_rel[0].target_id) == (ATTENTION.id, GAT.id)


def test_critiques_becomes_a_limitation_edge_so_gap_detection_has_input():
    relations, _ = collect_relations(
        [
            extraction(
                "p1",
                concepts=[ConceptMention(name="graph convolutional networks", role="uses")],
                relation=RelationType.CRITIQUES,
                target="GAT",
            )
        ],
        CONCEPTS,
    )
    limit = [r for r in relations if r.edge_type is EdgeType.HAS_LIMITATION]
    assert [(r.source_id, r.target_id) for r in limit] == [("p1", GAT.id)]


def test_applies_to_a_new_domain_becomes_a_paper_uses_edge():
    relations, _ = collect_relations(
        [
            extraction(
                "p1",
                concepts=[ConceptMention(name="graph convolutional networks", role="uses")],
                relation=RelationType.APPLIES_TO_NEW_DOMAIN,
                target="attention",
            )
        ],
        CONCEPTS,
    )
    # One USES from the mention's own role, one from the relation mapping.
    assert [(r.source_id, r.target_id) for r in relations if r.edge_type is EdgeType.USES] == [
        ("p1", GCN.id),
        ("p1", ATTENTION.id),
    ]


def test_builds_on_produces_one_lineage_edge_per_introduced_concept():
    relations, _ = collect_relations(
        [
            extraction(
                "p1",
                concepts=[
                    ConceptMention(name="graph attention networks", role="introduces"),
                    ConceptMention(name="graph convolutional networks", role="introduces"),
                ],
                builds_on=["attention", "GAT"],
            )
        ],
        CONCEPTS,
    )
    lineage = {(r.source_id, r.target_id) for r in relations if r.edge_type is EdgeType.EXTENDS}
    assert lineage == {
        (ATTENTION.id, GAT.id),
        (ATTENTION.id, GCN.id),
        (GAT.id, GAT.id),  # builds on an alias of a concept it also introduces
        (GAT.id, GCN.id),
    }


def test_a_paper_that_introduces_nothing_forms_no_lineage_edge():
    relations, _ = collect_relations(
        [
            extraction(
                "p1",
                concepts=[ConceptMention(name="attention", role="uses")],
                builds_on=["graph attention networks"],
            )
        ],
        CONCEPTS,
    )
    assert [r for r in relations if r.edge_type is EdgeType.EXTENDS] == []


def test_every_edge_records_the_paper_it_came_from():
    relations, _ = collect_relations(
        [extraction("p42", concepts=[ConceptMention(name="attention")])], CONCEPTS
    )
    assert relations[0].evidence == "p42: role=uses"


# -- Honest reporting -----------------------------------------------------------


def test_an_unresolvable_target_is_reported_not_silently_dropped():
    _relations, unresolved = collect_relations(
        [
            extraction(
                "p1",
                concepts=[ConceptMention(name="attention", role="introduces")],
                builds_on=["transformer"],
            )
        ],
        CONCEPTS,
    )
    assert unresolved == [{"paper_id": "p1", "name": "transformer", "from": "builds_on"}]


def test_an_unresolvable_mention_is_reported_too():
    _relations, unresolved = collect_relations(
        [extraction("p1", concepts=[ConceptMention(name="gizmo")])], CONCEPTS
    )
    assert unresolved[0]["name"] == "gizmo"


def test_repeated_unresolved_targets_are_collapsed():
    _relations, unresolved = collect_relations(
        [
            extraction("p1", concepts=[ConceptMention(name="gizmo"), ConceptMention(name="gizmo")]),
            extraction("p1", concepts=[ConceptMention(name="gizmo")]),
        ],
        CONCEPTS,
    )
    assert len(unresolved) == 1


def test_papers_with_no_extraction_are_listed():
    graph, report = build_research_graph([paper("p1", 2018), paper("p2", 2020)], CONCEPTS, [])
    assert report["papers_without_extraction"] == ["p1", "p2"]
    assert stats(graph)["edges"] == 0


def test_the_report_counts_edges_by_type():
    _graph, report = build_research_graph(
        [paper("p1", 2018), paper("p2", 2020, references=["p1"])],
        CONCEPTS,
        [extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")])],
    )
    assert report["relations_by_type"]["INTRODUCES"] == 1
    assert report["citations"] == 1


# -- The gate -------------------------------------------------------------------


def test_the_built_graph_has_zero_temporal_violations():
    papers = [paper("old", 2010), paper("new", 2021)]
    extractions = [
        # Claims a 2010 paper extends a 2015 concept: impossible, must be dropped.
        extraction(
            "old",
            concepts=[ConceptMention(name="attention", role="introduces")],
            relation=RelationType.EXTENDS,
            target="graph attention networks",
        ),
        extraction("new", concepts=[ConceptMention(name="GAT", role="uses")]),
    ]
    graph, report = build_research_graph(papers, CONCEPTS, extractions)

    assert report["temporal_violations_dropped"] == 1
    assert enforce_temporal_constraints(graph) == []
    assert not graph.has_edge(GAT.id, ATTENTION.id, key="EXTENDS")


def test_legitimate_lineage_survives():
    papers = [paper("p1", 2016), paper("p2", 2021)]
    extractions = [
        extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")]),
        extraction(
            "p2",
            concepts=[ConceptMention(name="graph attention networks", role="introduces")],
            builds_on=["attention"],
        ),
    ]
    graph, report = build_research_graph(papers, CONCEPTS, extractions)

    assert report["temporal_violations_dropped"] == 0
    assert graph.has_edge(ATTENTION.id, GAT.id, key="EXTENDS")
    assert enforce_temporal_constraints(graph) == []


def test_every_node_and_edge_type_is_in_the_spec_schema():
    papers = [paper("p1", 2016), paper("p2", 2021, references=["p1"])]
    extractions = [
        extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")]),
        extraction(
            "p2",
            concepts=[
                ConceptMention(name="graph attention networks", role="introduces"),
                ConceptMention(name="graph convolutional networks", role="uses"),
            ],
            builds_on=["attention"],
            relation=RelationType.EXTENDS,
            target="attention",
        ),
    ]
    graph, _ = build_research_graph(papers, CONCEPTS, extractions)

    node_types = {d["type"] for _, d in graph.nodes(data=True)}
    edge_types = {d["type"] for _, _, d in graph.edges(data=True)}
    assert node_types <= {t.value for t in NodeType}
    assert edge_types <= {t.value for t in EdgeType}
    assert "CITES" in edge_types and "EXTENDS" in edge_types


def test_citation_edges_stay_marked_as_ground_truth():
    graph, _ = build_research_graph(
        [paper("p1", 2016), paper("p2", 2021, references=["p1"])],
        CONCEPTS,
        [extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")])],
    )
    assert graph.get_edge_data("p2", "p1", "CITES")["ground_truth"] is True
    assert graph.get_edge_data("p1", ATTENTION.id, "INTRODUCES")["ground_truth"] is False


def test_the_graph_round_trips_through_json_without_loss(tmp_path):
    papers = [paper("p1", 2016), paper("p2", 2021, references=["p1"])]
    extractions = [
        extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")]),
        extraction(
            "p2",
            concepts=[ConceptMention(name="graph attention networks", role="introduces")],
            builds_on=["attention"],
        ),
    ]
    graph, _ = build_research_graph(papers, CONCEPTS, extractions)
    json_path = tmp_path / "graph.json"
    graphml_path = tmp_path / "graph.graphml"

    from rla.pipeline.graph_build import save_graph

    save_graph(graph, json_path, graphml_path)
    reloaded = load(json_path)

    assert stats(reloaded) == stats(graph)
    assert set(reloaded.nodes) == set(graph.nodes)
    assert set(reloaded.edges(keys=True)) == set(graph.edges(keys=True))
    # Evidence and provenance are the point of the derived edges, so they must
    # survive the round trip, not just the topology.
    assert reloaded.get_edge_data("p2", GAT.id, "INTRODUCES")["evidence"] == "p2: role=introduces"
    assert reloaded.get_edge_data(ATTENTION.id, GAT.id, "EXTENDS")["evidence"] == (
        "p2: builds_on attention"
    )
    assert json_path.exists() and graphml_path.exists()


def test_graphml_also_round_trips(tmp_path):
    graph, _ = build_research_graph(
        [paper("p1", 2016), paper("p2", 2021, references=["p1"])],
        CONCEPTS,
        [extraction("p1", concepts=[ConceptMention(name="attention", role="introduces")])],
    )
    from rla.pipeline.graph_build import save_graph

    graphml_path = tmp_path / "graph.graphml"
    save_graph(graph, tmp_path / "graph.json", graphml_path)
    reloaded = nx.read_graphml(graphml_path)
    assert reloaded.number_of_nodes() == graph.number_of_nodes()
    assert reloaded.number_of_edges() == graph.number_of_edges()


# -- The stage ------------------------------------------------------------------


def _corpus() -> Corpus:
    return Corpus(
        title="graph agents",
        papers=[paper("p1", 2016), paper("p2", 2021, references=["p1"])],
    )


async def test_the_stage_persists_both_files_and_reports(tmp_path):
    p1 = paper("p1", 2016)
    p2 = paper("p2", 2021, references=["p1"])
    corpus = Corpus(title="graph agents", papers=[p1, p2])
    extractions = [
        extraction_for(p1, concepts=[ConceptMention(name="attention", role="introduces")]),
        extraction_for(
            p2,
            concepts=[ConceptMention(name="graph attention networks", role="introduces")],
            builds_on=["attention"],
        ),
    ]
    json_path, graphml_path = tmp_path / "graph.json", tmp_path / "graph.graphml"

    events = [
        evt
        async for evt in build_graph_stage(
            corpus, CONCEPTS, extractions, json_path, graphml_path
        )
    ]

    assert events[-1].phase is Phase.GRAPH
    assert events[-1].kind == "ok"
    assert json_path.exists() and graphml_path.exists()
    assert events[-1].payload["stats"]["nodes"] == 5
    assert events[-1].payload["path"] == str(json_path)


async def test_the_stage_refuses_to_build_without_resolved_concepts(tmp_path):
    events = [
        evt
        async for evt in build_graph_stage(
            _corpus(), [], [], tmp_path / "g.json", tmp_path / "g.graphml"
        )
    ]
    assert events[-1].kind == "pending"
    assert "resolution" in events[-1].message
    assert not (tmp_path / "g.json").exists()


async def test_a_surviving_temporal_violation_is_reported_as_an_error(tmp_path, monkeypatch):
    """The gate is zero violations, so the stage checks rather than just counts."""
    from rla.pipeline import graph_build

    def leaky_clean(graph):
        graph.add_edge(GAT.id, ATTENTION.id, key="EXTENDS", type="EXTENDS")
        return [(GAT.id, ATTENTION.id, EdgeType.EXTENDS)]

    monkeypatch.setattr(graph_build, "enforce_temporal_constraints", leaky_clean)
    p1 = paper("p1", 2016)
    p2 = paper("p2", 2021, references=["p1"])
    corpus = Corpus(title="graph agents", papers=[p1, p2])
    extractions = [
        extraction_for(p1, concepts=[ConceptMention(name="attention", role="introduces")]),
        extraction_for(p2, concepts=[ConceptMention(name="GAT", role="uses")]),
    ]
    events = [
        evt
        async for evt in build_graph_stage(
            corpus, CONCEPTS, extractions, tmp_path / "g.json", tmp_path / "g.graphml"
        )
    ]
    assert any(evt.kind == "error" for evt in events)


# -- Orchestrator wiring --------------------------------------------------------


class _TwoPaperSource:
    """Stands in for a real adapter so the wiring test needs no network."""

    name = "fake"
    requires_key = False

    async def search(self, query: str, limit: int) -> list[Paper]:
        # The citation edge rides on the paper itself: snowball only asks
        # citation-graph sources, and this stand-in is not one of them.
        return [
            paper("p1", 2016, sources=["fake"]),
            paper("p2", 2021, sources=["fake"], references=["p1"]),
        ]

    async def references(self, paper, limit):
        return ["p1"] if paper.id == "p2" else []

    async def citations(self, paper, limit):
        return []


async def test_graph_runs_after_resolve_and_lands_in_the_result(settings, cache, monkeypatch):
    monkeypatch.setattr(
        "rla.pipeline.acquisition.build_sources", lambda *a, **k: {"fake": _TwoPaperSource()}
    )
    from rla.pipeline.orchestrator import IMPLEMENTED_PHASES, Pipeline, PipelineResult

    # Keep it offline: with a key set, resolution would try to embed for real.
    settings.gemini_api_key = ""
    settings.extractions_path.parent.mkdir(parents=True, exist_ok=True)
    seed_paper = paper("p1", 2016, sources=["fake"])
    settings.extractions_path.write_text(
        extraction_for(
            seed_paper, concepts=[ConceptMention(name="attention", role="introduces")]
        ).model_dump_json()
        + "\n",
        "utf-8",
    )

    assert Phase.GRAPH in IMPLEMENTED_PHASES
    result = PipelineResult()
    events = [evt async for evt in Pipeline(settings, None, cache).run("t", result=result)]

    phases = [evt.phase for evt in events]
    assert phases == sorted(phases, key=lambda p: list(PHASE_ORDER).index(p))
    # Resolution recomputes concepts from the extraction store rather than
    # trusting concepts.json, which is only an artifact of the previous run.
    assert result.resolution["concepts"] == 1
    assert [c.name for c in result.concepts] == ["attention"]
    assert result.graph is not None
    assert result.graph_report["stats"]["nodes_Concept"] == 1
    assert result.graph.has_edge("p1", result.concepts[0].id, key="INTRODUCES")
    # The citation edge came from ground truth, not from an extraction.
    assert result.graph.has_edge("p2", "p1", key="CITES")
    assert settings.graph_json.exists()
    assert settings.graph_graphml.exists()


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
