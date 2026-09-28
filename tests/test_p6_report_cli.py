"""P6 CLI gate: `rla report` emits both sections with every claim cited.

The runner is used rather than calling `report()` directly, so argument parsing,
exit codes, and the console output are all covered. Every test gets its own
temporary data directory, and the CLI's `get_settings` is pointed at it, so the
real `data/` is never read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rla.cli import app
from rla.config import Settings
from rla.models import Concept, Corpus, EdgeType, Extraction, Paper, Relation
from rla.store.extraction_store import ExtractionStore
from rla.store.graph_store import build_graph, save

EXTRACTIONS = [
    {
        "paper_id": "p1",
        "paper_hash": "h1",
        "summary": "Dense attention over graph neighbourhoods.",
        "stated_limitation": "It does not scale to graphs with more than a few million edges.",
    },
    {
        "paper_id": "p2",
        "paper_hash": "h2",
        "summary": "Sparse attention patterns for large graphs.",
        "stated_limitation": "Sparse patterns are chosen heuristically rather than learned.",
    },
]


@pytest.fixture
def prepared(tmp_path: Path):
    """A complete data directory: corpus, extractions, graph."""
    settings = Settings(
        gemini_api_key="",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    settings.ensure_dirs()

    corpus = Corpus(
        title="Graph representation learning",
        papers=[
            Paper(id="p1", title="Graph Attention Networks", year=2018),
            Paper(id="p2", title="Scalable GAT", year=2021),
        ],
        queries=["graph attention"],
    )
    settings.corpus_path.write_text(corpus.model_dump_json(indent=2), "utf-8")

    store = ExtractionStore(settings.extractions_path)
    store.load()
    for row in EXTRACTIONS:
        store.add(Extraction.model_validate(row))

    graph, _ = build_graph(
        corpus.papers,
        [
            Concept(id="c:gat", name="graph attention networks", first_seen_year=2018),
            Concept(id="c:island", name="spectral graph methods", first_seen_year=2014),
        ],
        [
            Relation(source_id="p1", target_id="c:gat", edge_type=EdgeType.INTRODUCES),
            Relation(source_id="p2", target_id="c:gat", edge_type=EdgeType.USES),
            Relation(source_id="p1", target_id="c:island", edge_type=EdgeType.INTRODUCES),
        ],
    )
    save(graph, settings.graph_json, settings.graph_graphml)
    return settings


@pytest.fixture
def run_cli(monkeypatch, prepared):
    """Point the CLI at the prepared data directory, not the real one."""
    runner = CliRunner()
    monkeypatch.setattr("rla.cli.get_settings", lambda: prepared)

    def _run(*args: str):
        return runner.invoke(app, list(args))

    return _run


def test_report_emits_both_required_sections(run_cli):
    result = run_cli("report")
    assert result.exit_code == 0, result.output
    assert "Per-paper stated limitations" in result.output
    assert "Synthesised gaps, ranked" in result.output


def test_report_lists_each_paper_s_limitation(run_cli):
    result = run_cli("report")
    assert "does not scale to graphs" in result.output
    assert "Sparse patterns are chosen heuristically" in result.output


def test_report_cites_every_ranked_claim(run_cli):
    result = run_cli("report")
    section = result.output.split("Synthesised gaps, ranked")[1]
    claims = [
        line for line in section.splitlines()
        if line.strip() and line.lstrip()[0].isdigit() and "**" in line
    ]
    assert claims
    for line in claims:
        assert "[" in line, f"uncited claim: {line}"


def test_report_includes_a_structural_gap_from_the_graph(run_cli):
    """`spectral graph methods` is 2014 and unbuilt-upon, so it must appear."""
    result = run_cli("report")
    assert "spectral graph methods" in result.output


def test_report_needs_no_api_key(run_cli, monkeypatch):
    """The whole point: gaps are read from disk, not generated."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = run_cli("report")
    assert result.exit_code == 0, result.output
    assert "no GEMINI_API_KEY" not in result.output


def test_report_json_is_machine_readable(run_cli):
    result = run_cli("report", "--jsonl")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["papers_considered"] == 2
    assert payload["papers_with_limitations"] == 2
    assert len(payload["per_paper"]) == 2
    assert payload["gaps"]
    for gap in payload["gaps"]:
        assert gap["citations"]


def test_report_json_gaps_all_resolve_to_a_label(run_cli):
    payload = json.loads(run_cli("report", "--jsonl").output)
    labels = {row["label"] for row in payload["per_paper"]}
    labels |= {g["label"] for g in payload["structural"]}
    for gap in payload["gaps"]:
        for citation in gap["citations"]:
            assert citation in labels, f"{citation} is not a resolvable label"


def test_report_fails_clearly_without_a_corpus(monkeypatch, tmp_path):
    settings = Settings(
        gemini_api_key="", data_dir=tmp_path, raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph"
    )
    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)
    result = CliRunner().invoke(app, ["report"])
    assert result.exit_code == 1
    assert "no corpus at" in result.output


def test_report_says_so_when_nothing_can_be_grounded(monkeypatch, tmp_path):
    """An empty extraction store must not produce invented gaps."""
    settings = Settings(
        gemini_api_key="", data_dir=tmp_path, raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph"
    )
    settings.ensure_dirs()
    empty = Corpus(title="Empty", papers=[Paper(id="p1", title="Only Paper", year=2020)])
    settings.corpus_path.write_text(empty.model_dump_json(), "utf-8")
    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)
    result = CliRunner().invoke(app, ["report"])
    assert result.exit_code == 0, result.output
    assert "No paper in the corpus states a limitation" in result.output
    assert "No gap could be grounded" in result.output
