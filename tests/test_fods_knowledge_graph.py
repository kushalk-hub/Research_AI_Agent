from __future__ import annotations

import json
import multiprocessing
from queue import Empty

import pytest

from fods.knowledge_graph import (
    classify_inputs,
    eligibility_manifest,
    empty_snapshot,
    publish,
    query,
    update_snapshot,
    validate,
)
from fods.tools import segment_text
from rla.models import Paper


def _lock_process(lock_path, attempting, acquired, release):
    from fods.knowledge_graph import topic_lock

    attempting.set()
    with topic_lock(lock_path):
        acquired.set()
        release.wait(10)


def _persisted_update_process(lock_path, graph_path, papers, enrichments, start, errors):
    from fods.knowledge_graph import topic_lock, update_snapshot

    try:
        start.wait(10)
        with topic_lock(lock_path):
            snapshot = json.loads(graph_path.read_text(encoding="utf-8"))
            updated, _ = update_snapshot(snapshot, papers, enrichments)
            publish(graph_path, updated)
    except Exception as exc:  # surfaced in the parent test with process context
        errors.put(repr(exc))


def records():
    abstract = "Graph attention networks improve node classification. Evidence is reported."
    paper = Paper(id="p1", title="Paper One", abstract=abstract)
    paper.ensure_hash()
    segments = segment_text(abstract)
    papers = {paper.id: paper.model_dump(mode="json")}
    extraction = {
        "paper_id": paper.id,
        "paper_hash": paper.content_hash,
        "concepts": [
            {
                "text": " Graph Attention Networks ",
                "role": "uses",
                "evidence_segment_ids": [segments[0]["segment_id"]],
                "evidence_excerpt": segments[0]["text"],
            }
        ],
        "methods": [
            {
                "text": "GAT",
                "evidence_segment_ids": [segments[0]["segment_id"]],
                "evidence_excerpt": segments[0]["text"],
            }
        ],
        "findings": [
            {
                "text": "Improved node classification",
                "evidence_segment_ids": [segments[1]["segment_id"]],
                "evidence_excerpt": segments[1]["text"],
            }
        ],
        "limitations": [],
    }
    return papers, {paper.id: extraction}


def test_build_is_deterministic_and_evidence_is_validated():
    papers, enrichments = records()
    first, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    second, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]
    assert any(node["type"] == "EVIDENCE_SPAN" for node in first["nodes"].values())
    validate(first)


def test_incremental_update_skips_unchanged_and_is_idempotent():
    papers, enrichments = records()
    graph, first_stats = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    assert first_stats["processed"] == 1
    graph, no_op = update_snapshot(graph, papers, enrichments)
    assert no_op["processed"] == 0
    again, repeat = update_snapshot(graph, papers, enrichments)
    assert repeat["processed"] == 0
    assert graph["nodes"] == again["nodes"]
    assert graph["edges"] == again["edges"]


def test_query_is_bounded_indexed_and_returns_source_evidence(monkeypatch):
    import fods.knowledge_graph as knowledge_graph

    papers, enrichments = records()
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    monkeypatch.setattr(
        knowledge_graph,
        "validate",
        lambda _snapshot: (_ for _ in ()).throw(AssertionError("query did full validation")),
    )
    result = query(graph, kind="CONCEPT", value="graph attention networks", max_nodes=10)
    assert any(node["id"] == "p1" for node in result["nodes"])
    assert any(node["type"] == "EVIDENCE_SPAN" for node in result["nodes"])
    assert len(result["nodes"]) <= 10


def test_invalid_evidence_is_not_linked_and_failed_publish_keeps_previous(tmp_path):
    papers, enrichments = records()
    enrichments["p1"]["concepts"][0]["evidence_segment_ids"] = ["S999"]
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    assert not any(edge["type"] == "HAS_CONCEPT" for edge in graph["edges"].values())
    assert not any(
        node["type"] == "EVIDENCE_SPAN" and node["category"] == "concepts"
        for node in graph["nodes"].values()
    )
    target = tmp_path / "graph.json"
    target.write_text('{"last_good":true}', encoding="utf-8")
    with pytest.raises(ValueError):
        publish(
            target,
            {"schema_version": 1, "nodes": {}, "edges": {"e": {"source": "x", "target": "y"}}},
        )
    assert json.loads(target.read_text(encoding="utf-8")) == {"last_good": True}


@pytest.mark.parametrize(
    ("segment_ids", "excerpt", "expected_reason"),
    [
        ([], "some excerpt", "missing_or_malformed_segment_ids"),
        ("S001", "some excerpt", "missing_or_malformed_segment_ids"),
        (["S001", "S001"], "some excerpt", "duplicate_segment_ids"),
        (["S999"], "some excerpt", "unknown_segment_id"),
        (["S001"], "", "missing_excerpt"),
        (["S001"], "incorrect source wording", "excerpt_mismatch"),
    ],
)
def test_evidence_rejection_reasons_are_reported(segment_ids, excerpt, expected_reason):
    papers, enrichments = records()
    enrichments["p1"]["concepts"][0].update(
        evidence_segment_ids=segment_ids, evidence_excerpt=excerpt
    )

    graph, stats = update_snapshot(empty_snapshot("topic"), papers, enrichments)

    assert stats["rejected_evidence_items"][0]["reason"] == expected_reason
    assert not any(edge["type"] == "HAS_CONCEPT" for edge in graph["edges"].values())


def test_mixed_validity_keeps_only_grounded_items_and_persists_provenance(tmp_path):
    papers, enrichments = records()
    enrichments["p1"]["concepts"].append(
        {
            "text": "unsupported concept",
            "role": "uses",
            "evidence_segment_ids": ["S999"],
            "evidence_excerpt": "not in the paper",
        }
    )
    graph, stats = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    path = tmp_path / "mixed.json"
    publish(path, graph)
    reopened = json.loads(path.read_text(encoding="utf-8"))

    assert stats["rejected_evidence_count"] == 1
    assert any(edge["type"] == "HAS_CONCEPT" for edge in reopened["edges"].values())
    assert not any(
        node.get("label") == "unsupported concept" for node in reopened["nodes"].values()
    )
    assert not query(reopened, kind="CONCEPT", value="unsupported concept")["nodes"]
    evidence = [n for n in reopened["nodes"].values() if n["type"] == "EVIDENCE_SPAN"]
    assert evidence and all(n["enrichment_fingerprint"] for n in evidence)
    assert all(
        edge["enrichment_fingerprint"]
        for edge in reopened["edges"].values()
        if edge["type"] == "HAS_CONCEPT"
    )


def test_multiple_valid_segments_reconstruct_in_order():
    papers, enrichments = records()
    paper = Paper.model_validate(papers["p1"])
    segments = segment_text(paper.abstract)
    enrichments["p1"]["concepts"][0].update(
        evidence_segment_ids=[segments[0]["segment_id"], segments[1]["segment_id"]],
        evidence_excerpt=f"{segments[0]['text']} {segments[1]['text']}",
    )

    graph, stats = update_snapshot(empty_snapshot("topic"), papers, enrichments)

    assert stats["rejected_evidence_count"] == 0
    evidence = next(n for n in graph["nodes"].values() if n.get("category") == "concepts")
    assert evidence["segment_ids"] == ["S001", "S002"]


def test_paper_local_segment_ids_cannot_prove_independent_foreign_ownership():
    abstract = "Graph attention networks improve node classification. Evidence is reported."
    source = Paper(id="source-paper", title="Source", abstract=abstract)
    target = Paper(id="target-paper", title="Target", abstract=abstract)
    source.ensure_hash()
    target.ensure_hash()
    source_segments = segment_text(source.abstract)
    target_segments = segment_text(target.abstract)
    assert source_segments[0]["segment_id"] == target_segments[0]["segment_id"] == "S001"
    assert source_segments[0]["text"] == target_segments[0]["text"]

    papers = {
        source.id: source.model_dump(mode="json"),
        target.id: target.model_dump(mode="json"),
    }
    # The nested evidence is copied from the source enrichment, while the
    # application-owned parent identity/hash correctly name the target paper.
    enrichments = {
        target.id: {
            "paper_id": target.id,
            "paper_hash": target.content_hash,
            "concepts": [
                {
                    "text": "Graph attention networks",
                    "role": "uses",
                    "evidence_segment_ids": [source_segments[0]["segment_id"]],
                    "evidence_excerpt": source_segments[0]["text"],
                }
            ],
            "methods": [],
            "findings": [],
            "limitations": [],
        }
    }

    graph, stats = update_snapshot(empty_snapshot("topic"), papers, enrichments)

    assert stats["rejected_evidence_count"] == 0
    evidence = next(n for n in graph["nodes"].values() if n["type"] == "EVIDENCE_SPAN")
    assert evidence["paper_id"] == target.id
    assert evidence["paper_hash"] == target.content_hash
    assert set(source_segments[0]) == {"segment_id", "start_char", "end_char", "text"}


def test_changed_enrichment_replaces_only_that_papers_contributions():
    papers, enrichments = records()
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    changed = json.loads(json.dumps(enrichments))
    changed["p1"]["paper_hash"] = "changed-hash"
    changed["p1"]["concepts"] = []
    updated, stats = update_snapshot(graph, papers, changed)
    assert stats["changed"] == 1
    assert not any(edge["type"] == "HAS_CONCEPT" for edge in updated["edges"].values())


def test_citation_edges_require_both_exact_paper_ids():
    papers, enrichments = records()
    cited = json.loads(json.dumps(papers["p1"]))
    cited["id"] = "p2"
    citing = json.loads(json.dumps(papers["p1"]))
    citing["id"] = "p3"
    citing["references"] = ["p2", "unresolved-reference"]
    papers.update({"p2": cited, "p3": citing})
    for paper_id, source in (("p2", "p1"), ("p3", "p1")):
        enrichments[paper_id] = json.loads(json.dumps(enrichments[source]))
        enrichments[paper_id]["paper_id"] = paper_id
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    citations = [edge for edge in graph["edges"].values() if edge["type"] == "CITES"]
    assert len(citations) == 1
    assert citations[0]["source"] == "p3" and citations[0]["target"] == "p2"
    assert citations[0]["trust"] == "BIBLIOGRAPHIC"
    cited_by = query(graph, kind="CITED_BY", value="p2")
    assert {node["id"] for node in cited_by["nodes"]} == {"p2", "p3"}


def test_persisted_incremental_build_update_reopen_and_idempotency(tmp_path):
    papers, enrichments = records()
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    path = tmp_path / "graph.json"
    publish(path, graph)
    graph = json.loads(path.read_text(encoding="utf-8"))
    before_nodes, before_edges = set(graph["nodes"]), set(graph["edges"])
    assert query(graph, kind="CONCEPT", value="graph attention networks")["nodes"]

    unchanged, no_change = update_snapshot(graph, papers, enrichments)
    assert no_change["processed"] == 0
    assert set(unchanged["nodes"]) == before_nodes
    assert set(unchanged["edges"]) == before_edges

    new_papers, new_enrichments = records()
    paper = Paper(id="p2", title="Paper Two", abstract=new_papers["p1"]["abstract"])
    paper.ensure_hash()
    new_papers[paper.id] = paper.model_dump(mode="json")
    new_enrichments[paper.id] = json.loads(json.dumps(new_enrichments["p1"]))
    new_enrichments[paper.id].update(paper_id="p2", paper_hash=paper.content_hash)
    updated, metrics = update_snapshot(graph, new_papers, new_enrichments)
    assert metrics["processed"] == 1
    assert any(
        e["source"] == "p2" and e["type"] == "HAS_CONCEPT" for e in updated["edges"].values()
    )
    publish(path, updated)
    reopened = json.loads(path.read_text(encoding="utf-8"))
    assert query(reopened, kind="CONCEPT", value="graph attention networks")["nodes"]
    repeated, repeat_stats = update_snapshot(reopened, new_papers, new_enrichments)
    assert repeat_stats["processed"] == 0
    assert repeated["nodes"] == reopened["nodes"]
    assert repeated["edges"] == reopened["edges"]


def test_publication_failure_leaves_previous_snapshot_queryable(tmp_path, monkeypatch):
    import fods.knowledge_graph as kg

    papers, enrichments = records()
    graph, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    path = tmp_path / "graph.json"
    publish(path, graph)
    previous = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(kg.os, "replace", fail_replace)
    with pytest.raises(OSError):
        publish(path, {**graph, "manifest": {**graph["manifest"], "new": True}})
    assert path.read_bytes() == previous
    reopened = json.loads(path.read_text(encoding="utf-8"))
    assert query(reopened, kind="CONCEPT", value="graph attention networks")["nodes"]


def test_eligibility_manifest_explains_missing_hash_mismatch_and_inclusion():
    papers, enrichments = records()
    papers["p2"] = {"id": "p2", "content_hash": "", "title": "Missing hash"}
    papers["p3"] = {"id": "p3", "content_hash": "valid-hash", "title": "No enrichment"}
    papers["p4"] = {"id": "p4", "content_hash": "different-hash", "title": "Mismatch"}
    enrichments["p4"] = {"paper_id": "p4", "paper_hash": "old-hash"}
    manifest = eligibility_manifest(papers, enrichments)
    assert manifest["p1"]["status"] == "eligible"
    assert manifest["p2"]["reason"] == "missing content hash"
    assert manifest["p3"]["reason"] == "missing enrichment"
    assert manifest["p4"]["reason"] == "content hash mismatch"


def test_raw_classifier_distinguishes_missing_mismatch_invalid_and_partial(tmp_path):
    papers, valid = records()
    p = Paper(id="p2", title="Mismatch", abstract=papers["p1"]["abstract"])
    p.ensure_hash()
    mismatch = json.loads(json.dumps(valid["p1"]))
    mismatch.update(paper_id="p2", paper_hash="stale-hash")
    malformed_paper = Paper(id="p3", title="Malformed")
    malformed_paper.ensure_hash()
    malformed = {
        "paper_id": "p3",
        "paper_hash": malformed_paper.content_hash,
        "concepts": "not-a-list",
    }
    partial = json.loads(json.dumps(valid["p1"]))
    partial["concepts"].append(
        {
            "text": "bad evidence",
            "role": "uses",
            "evidence_segment_ids": ["S999"],
            "evidence_excerpt": "wrong",
        }
    )
    partial.update(paper_id="p4", paper_hash=papers["p1"]["content_hash"])
    context = {
        "papers": [
            papers["p1"],
            p.model_dump(mode="json"),
            {
                "id": "p3",
                "title": "Malformed",
                "abstract": "",
                "year": None,
                "authors": [],
                "venue": "",
                "doi": "",
                "url": "",
                "arxiv_id": "",
                "external_ids": {},
                "sources": [],
                "keywords": [],
                "citation_count": 0,
                "references": [],
                "citations": [],
                "relevance_score": None,
                "content_hash": malformed_paper.content_hash,
            },
            {**papers["p1"], "id": "p4"},
        ]
    }
    records_dir = tmp_path / "fods" / "enrichments"
    records_dir.mkdir(parents=True)
    artifacts = [
        {"topic": "topic", "paper_enrichments": [valid["p1"], mismatch, malformed, partial]},
        {"topic": "elsewhere", "paper_enrichments": []},
    ]
    for i, artifact in enumerate(artifacts):
        (records_dir / f"{i}.json").write_text(json.dumps(artifact), encoding="utf-8")
    _, selected, report = classify_inputs(tmp_path, "topic", context)
    assert report["papers"]["p2"]["status"] == "HASH_MISMATCH"
    assert report["papers"]["p3"]["status"] == "INVALID_SCHEMA"
    assert report["papers"]["p4"]["status"] == "PARTIALLY_ELIGIBLE"
    assert "p4" in selected
    assert report["papers"]["p4"]["valid_items"] > 0


def test_raw_classifier_reports_conflicts_duplicate_context_ids_and_malformed_files(tmp_path):
    papers, enrichments = records()
    conflicting = json.loads(json.dumps(enrichments["p1"]))
    conflicting["concepts"][0]["text"] = "different extraction"
    records_dir = tmp_path / "fods" / "enrichments"
    records_dir.mkdir(parents=True)
    (records_dir / "first.json").write_text(
        json.dumps({"topic": "topic", "paper_enrichments": [enrichments["p1"]]}),
        encoding="utf-8",
    )
    (records_dir / "second.json").write_text(
        json.dumps({"topic": "topic", "paper_enrichments": [conflicting]}),
        encoding="utf-8",
    )
    (records_dir / "broken.json").write_text("{", encoding="utf-8")
    context = {"papers": [papers["p1"], papers["p1"]]}

    _, selected, report = classify_inputs(tmp_path, "topic", context)

    assert report["papers"]["p1"]["status"] == "DUPLICATE_OR_AMBIGUOUS"
    assert report["papers"]["p1"]["hash_match"] is None
    assert report["papers"]["p1"]["reason"] == "duplicate paper ID in context"
    assert report["duplicate_context_ids"] == ["p1"]
    assert report["totals"]["DUPLICATE_OR_AMBIGUOUS"] == 2
    assert report["malformed_artifacts_unattributable"] == 1
    assert report["raw_topic_artifacts"] == 2
    assert "p1" not in selected


def test_raw_classifier_marks_conflicting_artifacts_ambiguous(tmp_path):
    papers, enrichments = records()
    changed = json.loads(json.dumps(enrichments["p1"]))
    changed["concepts"][0]["text"] = "different matching record"
    records_dir = tmp_path / "fods" / "enrichments"
    records_dir.mkdir(parents=True)
    for name, item in (("a.json", enrichments["p1"]), ("b.json", changed)):
        (records_dir / name).write_text(
            json.dumps({"topic": "topic", "paper_enrichments": [item]}), encoding="utf-8"
        )

    _, selected, report = classify_inputs(tmp_path, "topic", {"papers": [papers["p1"]]})

    result = report["papers"]["p1"]
    assert result["status"] == "DUPLICATE_OR_AMBIGUOUS"
    assert result["hash_match"] is True
    assert result["artifact_count"] == 2
    assert len(result["artifact_refs"]) == 2
    assert "p1" not in selected


def test_topic_lock_serializes_real_processes_and_is_topic_scoped(tmp_path):
    from fods.knowledge_graph import topic_lock

    ctx = multiprocessing.get_context("spawn")
    lock_a = tmp_path / "topic-a.lock"
    attempting, acquired, release = ctx.Event(), ctx.Event(), ctx.Event()
    with topic_lock(lock_a):
        process = ctx.Process(target=_lock_process, args=(lock_a, attempting, acquired, release))
        process.start()
        assert attempting.wait(5)
        assert not acquired.wait(0.25)
        # Different-topic lock is independent while the first topic is held.
        with topic_lock(tmp_path / "topic-b.lock"):
            pass
    assert acquired.wait(5)
    release.set()
    process.join(5)
    assert process.exitcode == 0


def test_topic_lock_releases_after_exception_and_process_exit(tmp_path):
    from fods.knowledge_graph import topic_lock

    lock_path = tmp_path / "recover.lock"
    with pytest.raises(RuntimeError, match="forced update failure"):
        with topic_lock(lock_path):
            raise RuntimeError("forced update failure")
    with topic_lock(lock_path):
        pass

    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    process = ctx.Process(target=_lock_then_exit, args=(lock_path, ready, release))
    process.start()
    assert ready.wait(5)
    process.terminate()
    process.join(5)
    assert process.exitcode is not None
    with topic_lock(lock_path):
        pass


def test_topic_lock_open_failure_names_the_lock_path(tmp_path):
    from fods.knowledge_graph import topic_lock

    lock_path = tmp_path / "directory-is-not-a-file"
    lock_path.mkdir()
    with pytest.raises(OSError, match="could not open graph mutation lock"):
        with topic_lock(lock_path):
            pass


def test_concurrent_persisted_updates_keep_both_papers(tmp_path):
    papers, enrichments = records()
    initial, _ = update_snapshot(empty_snapshot("topic"), papers, enrichments)
    graph_path = tmp_path / "graph.json"
    publish(graph_path, initial)
    lock_path = tmp_path / "topic.lock"

    additions = {}
    for paper_id in ("p2", "p3"):
        paper = Paper(id=paper_id, title=f"Paper {paper_id}", abstract=papers["p1"]["abstract"])
        paper.ensure_hash()
        new_paper = paper.model_dump(mode="json")
        new_enrichment = json.loads(json.dumps(enrichments["p1"]))
        new_enrichment.update(paper_id=paper_id, paper_hash=paper.content_hash)
        additions[paper_id] = (new_paper, new_enrichment)

    shared_papers = dict(papers)
    shared_enrichments = dict(enrichments)
    for paper_id, (new_paper, new_enrichment) in additions.items():
        shared_papers[paper_id] = new_paper
        shared_enrichments[paper_id] = new_enrichment

    ctx = multiprocessing.get_context("spawn")
    start, errors = ctx.Event(), ctx.Queue()
    processes = [
        ctx.Process(
            target=_persisted_update_process,
            args=(
                lock_path,
                graph_path,
                shared_papers,
                shared_enrichments,
                start,
                errors,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    error_messages = []
    try:
        while True:
            error_messages.append(errors.get_nowait())
    except Empty:
        pass
    assert not error_messages, error_messages

    reopened = json.loads(graph_path.read_text(encoding="utf-8"))
    validate(reopened)
    assert {"p1", "p2", "p3"}.issubset(reopened["nodes"])
    assert {
        edge["source"] for edge in reopened["edges"].values() if edge["type"] == "HAS_CONCEPT"
    } >= {"p1", "p2", "p3"}


def _lock_then_exit(lock_path, ready, release):
    from fods.knowledge_graph import topic_lock

    with topic_lock(lock_path):
        ready.set()
        release.wait(10)
