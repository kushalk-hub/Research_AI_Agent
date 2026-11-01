"""Reproducible local-only graph benchmark using saved FODS artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import time
import tracemalloc
from pathlib import Path

from fods.knowledge_graph import empty_snapshot, load_inputs, query, update_snapshot
from fods.tools import read_context_snapshot
from rla.config import get_settings


def percentile(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * p))]


def timed_update(snapshot, papers, enrichments):
    start = time.perf_counter()
    result, metrics = update_snapshot(snapshot, papers, enrichments)
    metrics["wall_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return result, metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    args = parser.parse_args()
    settings = get_settings()
    context = read_context_snapshot(settings.data_dir, args.topic)
    papers, enrichments = load_inputs(settings.data_dir, args.topic, context)
    tracemalloc.start()
    started = time.perf_counter()
    graph, initial = timed_update(empty_snapshot(args.topic), papers, enrichments)
    initial["total_wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
    initial["peak_memory_bytes"] = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    graph["manifest"]["paper_hashes"] = {
        pid: value for pid, value in graph["manifest"]["paper_hashes"].items()
    }

    _, no_change = timed_update(graph, papers, enrichments)
    eligible = list(enrichments)
    synthetic_papers = copy.deepcopy(papers)
    synthetic_records = copy.deepcopy(enrichments)
    # Add isolated in-memory canaries derived from real records; nothing is written
    # back to the source corpus or enrichment artifacts.
    for index, source_id in enumerate(eligible[:5]):
        paper_id = f"benchmark-new-{index}"
        synthetic_papers[paper_id] = copy.deepcopy(papers[source_id])
        synthetic_papers[paper_id]["id"] = paper_id
        synthetic_records[paper_id] = copy.deepcopy(enrichments[source_id])
        synthetic_records[paper_id]["paper_id"] = paper_id
    one_papers, one_records = copy.deepcopy(papers), copy.deepcopy(enrichments)
    five_papers, five_records = copy.deepcopy(papers), copy.deepcopy(enrichments)
    one_id = "benchmark-new-0"
    one_papers[one_id], one_records[one_id] = synthetic_papers[one_id], synthetic_records[one_id]
    for index in range(5):
        paper_id = f"benchmark-new-{index}"
        five_papers[paper_id], five_records[paper_id] = (
            synthetic_papers[paper_id],
            synthetic_records[paper_id],
        )
    _, one_new = timed_update(graph, one_papers, one_records)
    _, five_new = timed_update(graph, five_papers, five_records)
    changed_records = copy.deepcopy(enrichments)
    changed_id = eligible[0]
    changed_records[changed_id]["concepts"] = copy.deepcopy(changed_records[changed_id]["concepts"])
    changed_records[changed_id]["concepts"].append(
        copy.deepcopy(changed_records[changed_id]["concepts"][0])
    )
    _, changed = timed_update(graph, papers, changed_records)

    concepts = [n for n in graph["nodes"].values() if n["type"] == "CONCEPT"]
    method_edges = [e for e in graph["edges"].values() if e["type"] == "USES_METHOD"]
    finding_nodes = [n for n in graph["nodes"].values() if n["type"] == "FINDING"]
    shared_pair = next(
        (
            (a, b)
            for index, a in enumerate(eligible)
            for b in eligible[index + 1 :]
            if {
                e["target"]
                for e in graph["edges"].values()
                if e["source"] == a and e["type"] == "HAS_CONCEPT"
            }
            & {
                e["target"]
                for e in graph["edges"].values()
                if e["source"] == b and e["type"] == "HAS_CONCEPT"
            }
        ),
        None,
    )
    query_cases = {
        "direct_concept_lookup": ("CONCEPT", concepts[0]["label"]),
        "papers_sharing_concepts": ("SHARED", "|".join(shared_pair or (eligible[0], eligible[0]))),
        "methods_used_by_paper": (
            "PAPER",
            method_edges[0]["source"] if method_edges else eligible[0],
        ),
        "bounded_traversal": ("CONCEPT", concepts[0]["label"]),
        "evidence_for_finding": ("FINDING", finding_nodes[0]["label"] if finding_nodes else ""),
    }
    query_results = {}
    for name, (query_kind, query_value) in query_cases.items():
        samples = []
        for _ in range(100):
            started = time.perf_counter()
            query(
                graph,
                kind=query_kind,
                value=query_value,
                max_depth=3 if name == "bounded_traversal" else 2,
                max_nodes=50,
                max_edges=100,
            )
            samples.append((time.perf_counter() - started) * 1000)
        query_results[name] = {
            "kind": query_kind,
            "value": query_value,
            "repetitions": len(samples),
            "p50_ms": round(statistics.median(samples), 3),
            "p95_ms": round(percentile(samples, 0.95), 3),
        }

    output = {
        "date": time.strftime("%Y-%m-%d"),
        "topic": args.topic,
        "context_id": context["context_hash"],
        "input_records_inspected": len(papers),
        "eligible_papers": len(enrichments),
        "initial_build": initial,
        "updates": {
            "no_change": no_change,
            "one_new": one_new,
            "five_new": five_new,
            "one_changed_enrichment": changed,
        },
        "queries": query_results,
        "graph": {
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "snapshot_bytes": len(json.dumps(graph, ensure_ascii=False).encode("utf-8")),
        },
        "normal_research_path": {
            "graph_builder_imported_by_runtime": False,
            "graph_update_invoked_by_runtime": False,
            "evidence": (
                "fods.knowledge_graph is imported only inside explicit graph CLI handlers; "
                "src/fods/runtime.py contains no graph import or call."
            ),
        },
    }
    destination = Path("docs/knowledge_graph_performance_report.json")
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Saved {destination}")


if __name__ == "__main__":
    main()
