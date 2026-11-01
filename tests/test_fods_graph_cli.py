from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from fods import cli
from fods.tools import segment_text
from rla.models import Paper, content_hash

TOPIC = "isolated graph update verification"


def _paper_and_enrichment(paper_id: str, version: int = 0):
    abstract = "Graph attention networks improve node classification. Evidence is reported."
    paper = Paper(id=paper_id, title=f"Paper {paper_id}", abstract=abstract)
    paper.ensure_hash()
    first, second = segment_text(abstract)
    concept = {
        "text": f"Graph attention networks {version}" if version else "Graph attention networks",
        "role": "uses",
        "evidence_segment_ids": [first["segment_id"]],
        "evidence_excerpt": first["text"],
    }
    return paper.model_dump(mode="json"), {
        "paper_id": paper_id,
        "paper_hash": paper.content_hash,
        "concepts": [concept],
        "methods": [
            {
                "text": "GAT",
                "evidence_segment_ids": [first["segment_id"]],
                "evidence_excerpt": first["text"],
            }
        ],
        "findings": [
            {
                "text": f"Improved node classification {version}"
                if version
                else "Improved node classification",
                "evidence_segment_ids": [second["segment_id"]],
                "evidence_excerpt": second["text"],
            }
        ],
        "limitations": [],
    }


def _save_inputs(data_dir: Path, papers: dict, enrichments: dict) -> None:
    context_root = data_dir / "fods" / "topics"
    topic_key = content_hash(TOPIC)[:16]
    version_dir = context_root / topic_key
    version_dir.mkdir(parents=True, exist_ok=True)
    context = {"schema_version": 3, "papers": list(papers.values())}
    context_id = content_hash(TOPIC, json.dumps(context, sort_keys=True))
    context["context_hash"] = context_id
    (version_dir / f"{context_id}.json").write_text(json.dumps(context), encoding="utf-8")
    (context_root / f"{topic_key}.latest").write_text(context_id, encoding="utf-8")

    enrichment_dir = data_dir / "fods" / "enrichments"
    enrichment_dir.mkdir(parents=True, exist_ok=True)
    (enrichment_dir / "isolated.json").write_text(
        json.dumps({"topic": TOPIC, "paper_enrichments": list(enrichments.values())}),
        encoding="utf-8",
    )


def test_cli_persisted_build_incremental_updates_and_publication_rollback(tmp_path, monkeypatch):
    from fods import knowledge_graph as kg

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    runner = CliRunner()
    papers, enrichments = {}, {}

    def add_papers(ids):
        for paper_id in ids:
            papers[paper_id], enrichments[paper_id] = _paper_and_enrichment(paper_id)
        _save_inputs(tmp_path, papers, enrichments)

    add_papers(["p0"])
    build = runner.invoke(cli.app, ["graph", "build", "--topic", TOPIC])
    assert build.exit_code == 0, build.output

    graph_path = tmp_path / "fods" / "knowledge_graph" / content_hash(TOPIC)[:16] / "graph.json"
    initial = json.loads(graph_path.read_text(encoding="utf-8"))
    assert "p0" in initial["nodes"]

    no_change = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert no_change.exit_code == 0, no_change.output
    add_papers(["p1"])
    one_new = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert one_new.exit_code == 0, one_new.output
    add_papers(["p2", "p3", "p4", "p5", "p6"])
    five_new = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert five_new.exit_code == 0, five_new.output

    changed_paper, changed = _paper_and_enrichment("p0", version=1)
    papers["p0"], enrichments["p0"] = changed_paper, changed
    _save_inputs(tmp_path, papers, enrichments)
    changed_result = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert changed_result.exit_code == 0, changed_result.output
    repeated = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert repeated.exit_code == 0, repeated.output

    enrichments["p0"]["concepts"][0]["evidence_segment_ids"] = ["S999"]
    _save_inputs(tmp_path, papers, enrichments)
    rejected_evidence = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert rejected_evidence.exit_code == 0, rejected_evidence.output
    graph_with_rejected_item = json.loads(graph_path.read_text(encoding="utf-8"))
    assert not any(
        edge["paper_id"] == "p0" and edge["type"] == "HAS_CONCEPT"
        for edge in graph_with_rejected_item["edges"].values()
    )

    before_failure = graph_path.read_bytes()

    papers["p0"]["content_hash"] = "stale-context-hash"
    _save_inputs(tmp_path, papers, enrichments)
    hash_mismatch = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert hash_mismatch.exit_code != 0
    assert graph_path.read_bytes() == before_failure
    papers["p0"], _ = _paper_and_enrichment("p0", version=1)
    _save_inputs(tmp_path, papers, enrichments)

    def fail_publish(*_args, **_kwargs):
        raise OSError("simulated CLI publication failure")

    monkeypatch.setattr(kg, "publish", fail_publish)
    failed = runner.invoke(cli.app, ["graph", "update", "--topic", TOPIC])
    assert failed.exit_code != 0
    assert graph_path.read_bytes() == before_failure
    reopened = json.loads(graph_path.read_text(encoding="utf-8"))
    kg.validate(reopened)
    assert {f"p{i}" for i in range(7)}.issubset(reopened["nodes"])

    report_path = graph_path.with_name("performance.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["updates"]) == 6
    assert all("elapsed_ms" in update and "total_ms" in update for update in report["updates"])
    assert report["updates"][0]["processed"] == 0
    assert report["updates"][1]["new"] == 1
    assert report["updates"][2]["new"] == 5
    assert report["updates"][3]["changed"] == 1
    assert report["updates"][4]["processed"] == 0
    assert report["updates"][5]["rejected_evidence_count"] == 1
    assert report["updates"][5]["eligibility"]["papers"]["p0"]["status"] == ("PARTIALLY_ELIGIBLE")
