from __future__ import annotations

import csv
import json

from fods.benchmark import collect_review_pack, score_review_pack


def test_review_pack_has_candidate_provenance_and_blank_human_labels(tmp_path):
    events = [
        {
            "seq": 1,
            "kind": "run_started",
            "payload": {
                "run_id": "run-1",
                "mode": "simulate",
                "topic": "Graph attention",
                "question": "Compare graph attention methods",
                "research_profile": {"profile": "quick"},
            },
            "timestamp": 1793210496.0368512,
        },
        {
            "seq": 2,
            "kind": "tool_call_validated",
            "payload": {
                "task_id": "search_openalex",
                "tool": "search_openalex",
                "arguments": {"query": "graph attention comparison", "limit": 10},
            },
        },
        {
            "seq": 3,
            "kind": "tool_call_completed",
            "payload": {
                "task_id": "search_openalex",
                "tool": "search_openalex",
                "output_summary": {
                    "papers": [
                        {
                            "id": "doi:10.1234/paper",
                            "title": "Graph Attention Methods",
                            "year": 2022,
                            "abstract": "A short paper abstract.",
                            "doi": "10.1234/paper",
                            "url": "https://example.org/paper",
                            "sources": ["openalex"],
                        }
                    ]
                },
            },
        },
        {
            "seq": 4,
            "kind": "evidence_selected",
            "payload": {"evidence": [{"citation": "P1", "paper": {"id": "doi:10.1234/paper"}}]},
        },
        {
            "seq": 5,
            "kind": "citation_validation",
            "payload": {"valid": True, "found": ["P1"], "allowed": ["P1"]},
        },
        {
            "seq": 6,
            "kind": "model_call_completed",
            "payload": {"stage": "fods_answer", "provider": "ollama", "model": "ollama/qwen3:4b"},
        },
    ]
    log = tmp_path / "run.jsonl"
    log.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    output = tmp_path / "review.csv"

    rows = collect_review_pack([log], output)

    assert len(rows) == 1
    with output.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["profile"] == "quick"
    assert row["sources"] == "openalex"
    assert row["queries"] == "graph attention comparison"
    assert row["citation_ids"] == "P1"
    assert row["selected_evidence_ids"] == "P1"
    assert row["run_started_at_utc"].startswith("2026-10-28T")
    assert row["models_used"] == "fods_answer:ollama:ollama/qwen3:4b"
    assert row["reviewer_label"] == ""
    assert row["reviewer_notes"] == ""


def test_scorer_does_not_invent_labels_or_recall(tmp_path):
    pack = tmp_path / "review.csv"
    fields = ["query_id", "profile", "rank", "reviewer_label", "judged_pool_complete"]
    with pack.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "query_id": "q1",
                    "profile": "quick",
                    "rank": 1,
                    "reviewer_label": "",
                    "judged_pool_complete": "false",
                },
                {
                    "query_id": "q1",
                    "profile": "quick",
                    "rank": 2,
                    "reviewer_label": "relevant",
                    "judged_pool_complete": "false",
                },
            ]
        )

    report = score_review_pack(pack, k_values=[1, 2])

    metrics = report["groups"]["q1/quick"]
    assert metrics["reviewed_candidates"] == 1
    assert metrics["precision_at_k"]["1"]["value"] is None
    assert metrics["precision_at_k"]["2"]["value"] == 1.0
    assert metrics["recall_at_k"]["2"] is None
    assert report["quality_verdict"] == "PENDING HUMAN REVIEW"


def test_uncertain_labels_are_excluded_from_binary_precision_and_withhold_recall(tmp_path):
    pack = tmp_path / "review.csv"
    fields = [
        "row_type",
        "query_id",
        "profile",
        "run_id",
        "rank",
        "reviewer_label",
        "judged_pool_complete",
        "acquisition_elapsed_ms",
        "total_elapsed_ms",
    ]
    with pack.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "row_type": "candidate",
                    "query_id": "Q1",
                    "profile": "quick",
                    "run_id": "one-run",
                    "rank": 1,
                    "reviewer_label": "relevant",
                    "judged_pool_complete": "true",
                    "acquisition_elapsed_ms": 100,
                    "total_elapsed_ms": 200,
                },
                {
                    "row_type": "candidate",
                    "query_id": "Q1",
                    "profile": "quick",
                    "run_id": "one-run",
                    "rank": 2,
                    "reviewer_label": "uncertain",
                    "judged_pool_complete": "true",
                    "acquisition_elapsed_ms": 100,
                    "total_elapsed_ms": 200,
                },
                {
                    "row_type": "candidate",
                    "query_id": "Q1",
                    "profile": "quick",
                    "run_id": "one-run",
                    "rank": 3,
                    "reviewer_label": "not_relevant",
                    "judged_pool_complete": "true",
                    "acquisition_elapsed_ms": 100,
                    "total_elapsed_ms": 200,
                },
            ]
        )

    metrics = score_review_pack(pack, k_values=[3])["groups"]["Q1/quick"]

    assert metrics["precision_at_k"]["3"] == {
        "value": 0.5,
        "relevant": 1,
        "reviewed_denominator": 2,
        "requested_k": 3,
    }
    assert metrics["recall_at_k"]["3"] is None
    assert metrics["acquisition_latency"]["run_denominator"] == 1
    assert metrics["total_latency"]["run_denominator"] == 1


def test_empty_failed_run_remains_visible_in_the_review_pack(tmp_path):
    log = tmp_path / "empty.jsonl"
    events = [
        {
            "kind": "run_started",
            "payload": {
                "run_id": "failed-run",
                "mode": "live",
                "topic": "GAT",
                "question": "What failed?",
            },
        },
        {
            "kind": "run_finished",
            "payload": {
                "succeeded": False,
                "termination_reason": "source_quorum_not_met",
                "elapsed_ms": 15,
            },
        },
    ]
    log.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    pack = tmp_path / "review.csv"
    rows = collect_review_pack([log], pack)
    report = score_review_pack(pack)

    assert rows[0]["row_type"] == "run_summary"
    assert rows[0]["run_succeeded"] == "false"
    metrics = report["groups"][f"{rows[0]['query_id']}/unknown"]
    assert metrics["unique_candidates"] == 0
    assert metrics["failed_runs"] == 1


def test_collect_refuses_to_overwrite_existing_human_review_file(tmp_path):
    log = tmp_path / "empty.jsonl"
    log.write_text("", encoding="utf-8")
    output = tmp_path / "annotated.csv"
    output.write_text("reviewer_label\nrelevant\n", encoding="utf-8")

    try:
        collect_review_pack([log], output)
    except FileExistsError as exc:
        assert "choose a new output path" in str(exc)
    else:
        raise AssertionError("collector overwrote an existing annotation file")
    assert output.read_text(encoding="utf-8") == "reviewer_label\nrelevant\n"
