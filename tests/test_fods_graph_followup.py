from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from fods import cli
from fods.graph_followup import FollowupRoute, route_question, run_followup
from fods.knowledge_graph import empty_snapshot, publish, update_snapshot
from fods.tools import segment_text
from rla.models import Paper, content_hash


@pytest.mark.parametrize(
    ("question", "kind", "value"),
    [
        ("Which papers use GAT?", "METHOD", "GAT"),
        ("Which papers discuss graph attention networks?", "CONCEPT", "graph attention networks"),
        (
            "What findings are reported for graph attention networks?",
            "FINDING_FOR_TOPIC",
            "graph attention networks",
        ),
        (
            "What limitations are mentioned for graph attention networks?",
            "LIMITATION_FOR_TOPIC",
            "graph attention networks",
        ),
        ("Which papers cite doi:10.1234/example.1?", "CITED_BY", "doi:10.1234/example.1"),
        (
            "What concepts are shared between paper-a and paper-b?",
            "SHARED",
            "paper-a|paper-b",
        ),
    ],
)
def test_question_router_supports_bounded_query_forms(question, kind, value):
    assert route_question(question) == FollowupRoute(kind, value)


def test_question_router_returns_none_for_unsupported_or_ambiguous_questions():
    assert route_question("Does GAT cause better predictions?") is None
    assert route_question("Which papers cite this paper?") is None
    assert route_question("   ") is None


def _snapshot():
    abstract_a = (
        "Graph attention networks use neighbor attention. Evaluation was limited to two datasets."
    )
    abstract_b = "Graph attention networks improve classification. Evidence is reported."
    paper_a = Paper(
        id="paper-a",
        title="Graph Attention Networks",
        abstract=abstract_a,
        references=[],
    )
    paper_b = Paper(
        id="paper-b",
        title="A Follow-up Study",
        abstract=abstract_b,
        references=["paper-a"],
    )
    paper_a.ensure_hash()
    paper_b.ensure_hash()
    segments_a = segment_text(abstract_a)
    segments_b = segment_text(abstract_b)
    papers = {paper.id: paper.model_dump(mode="json") for paper in (paper_a, paper_b)}
    enrichments = {
        "paper-a": {
            "paper_id": "paper-a",
            "paper_hash": paper_a.content_hash,
            "concepts": [
                {
                    "text": "graph attention networks",
                    "role": "introduces",
                    "evidence_segment_ids": [segments_a[0]["segment_id"]],
                    "evidence_excerpt": segments_a[0]["text"],
                }
            ],
            "methods": [
                {
                    "text": "GAT",
                    "evidence_segment_ids": [segments_a[0]["segment_id"]],
                    "evidence_excerpt": segments_a[0]["text"],
                }
            ],
            "findings": [
                {
                    "text": "graph attention networks use neighbor attention",
                    "evidence_segment_ids": [segments_a[0]["segment_id"]],
                    "evidence_excerpt": segments_a[0]["text"],
                }
            ],
            "limitations": [
                {
                    "text": "limited to two datasets",
                    "evidence_segment_ids": [segments_a[1]["segment_id"]],
                    "evidence_excerpt": segments_a[1]["text"],
                }
            ],
        },
        "paper-b": {
            "paper_id": "paper-b",
            "paper_hash": paper_b.content_hash,
            "concepts": [
                {
                    "text": "graph attention networks",
                    "role": "uses",
                    "evidence_segment_ids": [segments_b[0]["segment_id"]],
                    "evidence_excerpt": segments_b[0]["text"],
                }
            ],
            "methods": [
                {
                    "text": "GAT",
                    "evidence_segment_ids": [segments_b[0]["segment_id"]],
                    "evidence_excerpt": segments_b[0]["text"],
                }
            ],
            "findings": [
                {
                    "text": "graph attention networks improve classification",
                    "evidence_segment_ids": [segments_b[0]["segment_id"]],
                    "evidence_excerpt": segments_b[0]["text"],
                }
            ],
            "limitations": [],
        },
    }
    graph, _ = update_snapshot(empty_snapshot("Graph attention networks"), papers, enrichments)
    return graph


def test_followup_returns_only_paper_linked_evidence_and_limits():
    answer = run_followup(
        _snapshot(),
        route_question("Which papers use GAT?"),
        max_nodes=10,
        max_edges=20,
        max_evidence=5,
    )

    assert answer["limits"] == {"max_depth": 3, "max_nodes": 10, "max_edges": 20, "max_evidence": 5}
    assert {record["paper_id"] for record in answer["evidence_records"]} == {
        "paper-a",
        "paper-b",
    }
    assert all(record["segment_ids"] and record["excerpt"] for record in answer["evidence_records"])
    assert all(record["relationship"] == "uses method" for record in answer["evidence_records"])
    assert {record["item"] for record in answer["evidence_records"]} == {"GAT"}
    assert answer["bibliographic_records"] == []

    concepts = run_followup(
        _snapshot(),
        route_question("Which papers discuss graph attention networks?"),
    )
    assert concepts["evidence_records"]
    assert {record["item"] for record in concepts["evidence_records"]} == {
        "graph attention networks"
    }


@pytest.mark.parametrize(
    ("question", "relationship"),
    [
        ("What findings are reported for graph attention networks?", "reports finding"),
        ("What limitations are mentioned for graph attention networks?", "states limitation"),
    ],
)
def test_topic_findings_and_limitations_are_filtered_to_requested_relation(question, relationship):
    answer = run_followup(_snapshot(), route_question(question))
    assert answer["evidence_records"]
    assert {record["relationship"] for record in answer["evidence_records"]} == {relationship}


def test_followup_citation_and_shared_concept_wording_is_cautious():
    graph = _snapshot()
    citations = run_followup(graph, route_question("Which papers cite paper-a?"))
    assert citations["bibliographic_records"] == [
        {
            "citing_paper_id": "paper-b",
            "citing_paper_title": "A Follow-up Study",
            "cited_paper_id": "paper-a",
            "cited_paper_title": "Graph Attention Networks",
            "basis": "stored bibliographic reference",
        }
    ]
    shared = run_followup(
        graph,
        route_question("What concepts are shared between paper-a and paper-b?"),
    )
    assert "vocabulary overlap, not agreement" in shared["summary"]
    assert len(shared["evidence_records"]) >= 2


def test_followup_no_result_and_unsupported_responses_are_explicit():
    empty = run_followup(_snapshot(), route_question("Which papers use unknown method?"))
    assert empty["evidence_records"] == []
    assert "No matching" in empty["summary"]
    assert route_question("Does this method cause the finding?") is None


def test_cli_followup_reads_snapshot_and_returns_source_evidence(tmp_path, monkeypatch):
    topic = "Graph attention networks"
    graph = _snapshot()
    graph_path = tmp_path / "fods" / "knowledge_graph" / content_hash(topic)[:16] / "graph.json"
    publish(graph_path, graph)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "graph",
            "follow-up",
            "--topic",
            topic,
            "--question",
            "What findings are reported for graph attention networks?",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Graph Attention Networks (paper-a)" in result.output
    assert "Evidence S001:" in result.output
    assert "Graph attention networks use neighbor attention." in result.output

    limitations = runner.invoke(
        cli.app,
        [
            "graph",
            "follow-up",
            "--topic",
            topic,
            "--question",
            "What limitations are mentioned for graph attention networks?",
        ],
    )
    assert limitations.exit_code == 0, limitations.output
    assert "Found 1 evidence-backed graph record(s)." in limitations.output
    assert "states limitation: limited to two datasets" in limitations.output
    assert "Evidence S002: Evaluation was limited to two datasets." in limitations.output


def test_cli_followup_does_not_build_missing_graph_and_json_is_available(tmp_path, monkeypatch):
    topic = "No graph topic"
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    runner = CliRunner()
    missing = runner.invoke(
        cli.app,
        ["graph", "follow-up", "--topic", topic, "--question", "Which papers use GAT?"],
    )
    graph_path = tmp_path / "fods" / "knowledge_graph" / content_hash(topic)[:16] / "graph.json"
    assert missing.exit_code == 0
    assert "graph build" in missing.output
    assert not graph_path.exists()

    topic_with_graph = "Graph attention networks"
    graph_path = (
        tmp_path / "fods" / "knowledge_graph" / content_hash(topic_with_graph)[:16] / "graph.json"
    )
    publish(graph_path, _snapshot())
    result = runner.invoke(
        cli.app,
        [
            "graph",
            "follow-up",
            "--topic",
            topic_with_graph,
            "--question",
            "Which papers cite paper-a?",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["bibliographic_records"][0]["citing_paper_id"] == "paper-b"
