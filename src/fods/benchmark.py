"""Build human-review packs and score only labels supplied by a reviewer."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rla.models import content_hash
from rla.sources.base import normalise_doi, normalise_title

REVIEW_FIELDS = [
    "row_type",
    "query_id",
    "run_id",
    "run_started_at_utc",
    "mode",
    "profile",
    "topic",
    "question",
    "context_id",
    "context_built_at",
    "paper_identity",
    "paper_id",
    "title",
    "year",
    "abstract_excerpt",
    "abstract_is_excerpt",
    "url",
    "doi",
    "sources",
    "source_observation_count",
    "queries",
    "rank",
    "citation_ids",
    "selected_evidence_ids",
    "citation_validation_valid",
    "models_used",
    "reviewer_label",
    "reviewer_notes",
    "judged_pool_complete",
    "raw_candidate_count",
    "candidates_processed_count",
    "candidates_truncated_count",
    "duplicates_merged",
    "unique_paper_count",
    "retained_paper_count",
    "cache_policies",
    "successful_sources",
    "failed_sources",
    "cancelled_sources",
    "acquisition_elapsed_ms",
    "total_elapsed_ms",
    "run_succeeded",
    "run_termination_reason",
]


def _read_log(path: Path) -> list[dict[str, Any]]:
    events = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid event JSON at {path}:{line_no}") from exc
    return events


def _identity(paper: dict[str, Any]) -> str:
    if doi := normalise_doi(str(paper.get("doi", ""))):
        return f"doi:{doi}"
    if arxiv := str(paper.get("arxiv_id", "")).strip().lower():
        return f"arxiv:{arxiv}"
    external = paper.get("external_ids", {})
    if isinstance(external, dict) and external:
        namespace, value = sorted(external.items())[0]
        return f"{str(namespace).lower()}:{str(value).lower()}"
    title = normalise_title(str(paper.get("title", "")))
    return f"title-year:{content_hash(title, paper.get('year'))}"


def _query_id(question: str, query_set: dict[str, str]) -> str:
    normalized = " ".join(question.casefold().split())
    return query_set.get(normalized, f"adhoc-{content_hash(normalized)[:8]}")


def collect_review_pack(
    run_logs: list[Path], output: Path, query_file: Path | None = None
) -> list[dict[str, str]]:
    """Collect one candidate/profile/question row, preserving blank reviewer labels."""
    query_set: dict[str, str] = {}
    if query_file is not None:
        questions = json.loads(query_file.read_text(encoding="utf-8"))
        query_set = {
            " ".join(item["question"].casefold().split()): item["query_id"] for item in questions
        }
    rows: list[dict[str, str]] = []
    for log_path in run_logs:
        events = _read_log(log_path)
        start_event = next((e for e in events if e.get("kind") == "run_started"), {})
        start = start_event.get("payload", {})
        run_id = str(start.get("run_id", log_path.stem))
        started = float(start_event.get("timestamp", 0))
        run_started_at_utc = datetime.fromtimestamp(started, UTC).isoformat() if started else ""
        profile = start.get("research_profile", {})
        profile_name = str(profile.get("profile", "unknown"))
        question = str(start.get("question", ""))
        topic = str(start.get("topic", ""))
        mode = str(start.get("mode", "unknown"))
        papers: dict[str, dict[str, Any]] = {}
        provenance: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: {"sources": set(), "queries": set()}
        )
        observation_counts: dict[str, int] = defaultdict(int)
        selected_citations: dict[str, set[str]] = defaultdict(set)
        used_citations: set[str] = set()
        citation_validation_valid: Any = ""
        rank_by_identity: dict[str, int] = {}
        context_id = ""
        context_built_at = ""
        models_used: set[str] = set()
        context_counts: dict[str, Any] = {}
        cache_policies: set[str] = set()
        successful_sources: set[str] = set()
        failed_sources: set[str] = set()
        cancelled_sources: set[str] = set()
        source_started_at: float | None = None
        acquisition_elapsed_ms: Any = ""
        total_elapsed_ms: Any = ""
        run_succeeded: Any = ""
        termination_reason = ""
        for event in events:
            payload = event.get("payload", {})
            kind = event.get("kind")
            if kind == "model_call_completed":
                identity = [
                    str(payload[key]) for key in ("stage", "provider", "model") if payload.get(key)
                ]
                if identity:
                    models_used.add(":".join(identity))
            if kind == "tool_call_validated" and str(payload.get("tool", "")).startswith("search_"):
                timestamp = float(event.get("timestamp", 0))
                source_started_at = min(source_started_at or timestamp, timestamp)
            elif kind == "tool_call_completed" and str(payload.get("tool", "")).startswith(
                "search_"
            ):
                task_id = str(payload.get("task_id", ""))
                args_event = next(
                    (
                        item.get("payload", {}).get("arguments", {})
                        for item in events
                        if item.get("kind") == "tool_call_validated"
                        and item.get("payload", {}).get("task_id") == task_id
                    ),
                    {},
                )
                tool = str(payload.get("tool", "")).removeprefix("search_")
                source = re.sub(r"_q\d+$", "", tool)
                query = str(args_event.get("query", ""))
                successful_sources.add(source)
                cache_policy = str(payload.get("output_summary", {}).get("cache_policy", ""))
                if cache_policy:
                    cache_policies.add(cache_policy)
                for paper in payload.get("output_summary", {}).get("papers", []):
                    identity = _identity(paper)
                    papers.setdefault(identity, paper)
                    provenance[identity]["sources"].add(source)
                    observation_counts[identity] += 1
                    if query:
                        provenance[identity]["queries"].add(query)
            elif kind == "context_ready":
                context_id = str(payload.get("context_hash", ""))
                context_built_at = str(payload.get("context_built_at", ""))
                context_counts = {
                    name: payload.get(name, "")
                    for name in (
                        "raw_candidate_count",
                        "candidates_processed_count",
                        "candidates_truncated_count",
                        "duplicates_merged",
                        "unique_paper_count",
                        "retained_paper_count",
                    )
                }
                for rank, paper in enumerate(payload.get("papers", []), start=1):
                    identity = _identity(paper)
                    papers.setdefault(identity, paper)
                    rank_by_identity[identity] = rank
                    for source in paper.get("sources", []):
                        provenance[identity]["sources"].add(str(source))
                if source_started_at is not None:
                    acquisition_elapsed_ms = round(
                        (float(event.get("timestamp", 0)) - source_started_at) * 1000, 1
                    )
            elif kind == "evidence_selected":
                for evidence in payload.get("evidence", []):
                    paper_id = str(evidence.get("paper", {}).get("id", ""))
                    citation = str(evidence.get("citation", ""))
                    for identity, paper in papers.items():
                        if str(paper.get("id", "")) == paper_id and citation:
                            selected_citations[identity].add(citation)
            elif kind == "citation_validation":
                citation_validation_valid = str(bool(payload.get("valid"))).lower()
                used_citations.update(str(item) for item in payload.get("found", []))
            elif kind == "task_failed" and str(payload.get("task_id", "")).startswith("search_"):
                failed_sources.add(
                    re.sub(r"_q\d+$", "", str(payload["task_id"]).removeprefix("search_"))
                )
            elif kind == "task_cancelled" and str(payload.get("task_id", "")).startswith("search_"):
                cancelled_sources.add(
                    re.sub(r"_q\d+$", "", str(payload["task_id"]).removeprefix("search_"))
                )
            elif kind == "run_finished":
                total_elapsed_ms = payload.get("elapsed_ms", "")
                run_succeeded = str(bool(payload.get("succeeded"))).lower()
                termination_reason = str(payload.get("termination_reason", ""))
        qid = _query_id(question, query_set)
        emitted = 0
        for identity, paper in papers.items():
            abstract = " ".join(str(paper.get("abstract", "")).split())
            observations = provenance[identity]
            rows.append(
                {
                    "row_type": "candidate",
                    "query_id": qid,
                    "run_id": run_id,
                    "run_started_at_utc": run_started_at_utc,
                    "mode": mode,
                    "profile": profile_name,
                    "topic": topic,
                    "question": question,
                    "context_id": context_id,
                    "context_built_at": context_built_at,
                    "paper_identity": identity,
                    "paper_id": str(paper.get("id", "")),
                    "title": str(paper.get("title", "")),
                    "year": str(paper.get("year") or ""),
                    "abstract_excerpt": abstract[:1200],
                    "abstract_is_excerpt": str(len(abstract) > 1200).lower(),
                    "url": str(paper.get("url", "")),
                    "doi": str(paper.get("doi", "")),
                    "sources": ";".join(sorted(observations["sources"])),
                    "source_observation_count": str(max(1, observation_counts[identity])),
                    "queries": ";".join(sorted(observations["queries"])),
                    "rank": str(rank_by_identity.get(identity, "")),
                    "citation_ids": ";".join(sorted(selected_citations[identity] & used_citations)),
                    "selected_evidence_ids": ";".join(sorted(selected_citations[identity])),
                    "citation_validation_valid": str(citation_validation_valid),
                    "models_used": ";".join(sorted(models_used)),
                    "reviewer_label": "",
                    "reviewer_notes": "",
                    "judged_pool_complete": "false",
                    **{name: str(value) for name, value in context_counts.items()},
                    "cache_policies": ";".join(sorted(cache_policies)),
                    "successful_sources": ";".join(sorted(successful_sources)),
                    "failed_sources": ";".join(sorted(failed_sources)),
                    "cancelled_sources": ";".join(sorted(cancelled_sources)),
                    "acquisition_elapsed_ms": str(acquisition_elapsed_ms),
                    "total_elapsed_ms": str(total_elapsed_ms),
                    "run_succeeded": str(run_succeeded),
                    "run_termination_reason": termination_reason,
                }
            )
            emitted += 1
        if emitted == 0 and start:
            rows.append(
                {
                    "row_type": "run_summary",
                    "query_id": qid,
                    "run_id": run_id,
                    "run_started_at_utc": run_started_at_utc,
                    "mode": mode,
                    "profile": profile_name,
                    "topic": topic,
                    "question": question,
                    "context_id": context_id,
                    "context_built_at": context_built_at,
                    "paper_identity": "",
                    "paper_id": "",
                    "title": "",
                    "year": "",
                    "abstract_excerpt": "",
                    "abstract_is_excerpt": "false",
                    "url": "",
                    "doi": "",
                    "sources": ";".join(sorted(successful_sources)),
                    "source_observation_count": "0",
                    "queries": "",
                    "rank": "",
                    "citation_ids": "",
                    "selected_evidence_ids": "",
                    "citation_validation_valid": str(citation_validation_valid),
                    "models_used": ";".join(sorted(models_used)),
                    "reviewer_label": "",
                    "reviewer_notes": "",
                    "judged_pool_complete": "false",
                    **{name: str(value) for name, value in context_counts.items()},
                    "cache_policies": ";".join(sorted(cache_policies)),
                    "successful_sources": ";".join(sorted(successful_sources)),
                    "failed_sources": ";".join(sorted(failed_sources)),
                    "cancelled_sources": ";".join(sorted(cancelled_sources)),
                    "acquisition_elapsed_ms": str(acquisition_elapsed_ms),
                    "total_elapsed_ms": str(total_elapsed_ms),
                    "run_succeeded": str(run_succeeded),
                    "run_termination_reason": termination_reason,
                }
            )
    rows.sort(
        key=lambda item: (item["query_id"], item["profile"], item["rank"], item["paper_identity"])
    )
    if output.exists():
        raise FileExistsError(f"review pack already exists; choose a new output path: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _group_metrics(rows: list[dict[str, str]], k_values: list[int]) -> dict[str, Any]:
    rows.sort(key=lambda row: int(row["rank"] or 10**9))
    candidate_rows = [row for row in rows if row.get("row_type", "candidate") == "candidate"]
    reviewed = [
        row
        for row in candidate_rows
        if row.get("reviewer_label", "") in {"relevant", "not_relevant"}
    ]
    all_labels_present = bool(candidate_rows) and all(
        row.get("reviewer_label", "") in {"relevant", "not_relevant"} for row in candidate_rows
    )
    relevant = [row for row in reviewed if row.get("reviewer_label") == "relevant"]
    pool_complete = bool(candidate_rows) and all(
        row.get("judged_pool_complete", "false").lower() == "true" for row in candidate_rows
    )
    precision = {}
    recall = {}
    for k in k_values:
        top = [
            row
            for row in candidate_rows[:k]
            if row.get("reviewer_label", "") in {"relevant", "not_relevant"}
        ]
        precision[str(k)] = {
            "value": sum(row.get("reviewer_label") == "relevant" for row in top) / len(top)
            if top
            else None,
            "relevant": sum(row.get("reviewer_label") == "relevant" for row in top),
            "reviewed_denominator": len(top),
            "requested_k": k,
        }
        recall[str(k)] = (
            sum(row.get("reviewer_label") == "relevant" for row in top) / len(relevant)
            if pool_complete and all_labels_present and relevant
            else None
        )
    labels_filled = len(reviewed)
    runs = {}
    for row in rows:
        if row.get("run_id"):
            runs.setdefault(row["run_id"], row)
    acquisition_times = [
        float(row["acquisition_elapsed_ms"])
        for row in runs.values()
        if row.get("acquisition_elapsed_ms") not in {None, ""}
    ]
    total_times = [
        float(row["total_elapsed_ms"])
        for row in runs.values()
        if row.get("total_elapsed_ms") not in {None, ""}
    ]

    def latency(values: list[float]) -> dict[str, float | None]:
        ordered = sorted(values)
        return {
            "median_ms": statistics.median(ordered) if ordered else None,
            "p90_ms": ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)] if ordered else None,
            "run_denominator": len(ordered),
        }

    return {
        "unique_candidates": len(candidate_rows),
        "reviewed_candidates": labels_filled,
        "relevant_candidates": len(relevant),
        "uncertain_candidates": sum(row.get("reviewer_label") == "uncertain" for row in rows),
        "source_diversity": len(
            {source for row in rows for source in row.get("sources", "").split(";") if source}
        ),
        "duplicate_rate": (
            max(
                0,
                sum(int(row.get("source_observation_count", "1") or 1) for row in candidate_rows)
                - len(candidate_rows),
            )
            / max(
                1,
                sum(int(row.get("source_observation_count", "1") or 1) for row in candidate_rows),
            )
        ),
        "abstract_coverage": sum(bool(row.get("abstract_excerpt", "")) for row in candidate_rows)
        / len(candidate_rows)
        if candidate_rows
        else None,
        "candidate_truncation_count": max(
            (int(row.get("candidates_truncated_count", "0") or 0) for row in rows),
            default=0,
        ),
        "failed_source_count": len(
            {
                source
                for row in rows
                for source in row.get("failed_sources", "").split(";")
                if source
            }
        ),
        "unavailable_source_count": len(
            {
                source
                for row in rows
                for source in row.get("cancelled_sources", "").split(";")
                if source
            }
        ),
        "acquisition_latency": latency(acquisition_times),
        "total_latency": latency(total_times),
        "failed_runs": len(
            {
                row.get("run_id", "")
                for row in rows
                if row.get("run_succeeded") == "false" and row.get("run_id")
            }
        ),
        "selected_evidence_papers": sum(
            bool(row.get("selected_evidence_ids")) for row in candidate_rows
        ),
        "cited_papers": sum(bool(row.get("citation_ids")) for row in candidate_rows),
        "citation_validation_runs": len(
            {
                row.get("run_id", "")
                for row in rows
                if row.get("citation_validation_valid") in {"true", "false"} and row.get("run_id")
            }
        ),
        "citation_validation_invalid_runs": len(
            {
                row.get("run_id", "")
                for row in rows
                if row.get("citation_validation_valid") == "false" and row.get("run_id")
            }
        ),
        "precision_at_k": precision,
        "recall_at_k": recall,
        "judged_pool_complete": pool_complete,
    }


def score_review_pack(path: Path, k_values: list[int] | None = None) -> dict[str, Any]:
    """Compute transparent metrics from reviewer labels; never fills missing labels."""
    ks = sorted(set(k_values or [5, 10]))
    if not ks or any(k < 1 for k in ks):
        raise ValueError("k values must be positive")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    allowed = {"", "relevant", "not_relevant", "uncertain"}
    if any(row.get("reviewer_label", "") not in allowed for row in rows):
        raise ValueError("reviewer_label must be blank, relevant, not_relevant, or uncertain")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_profile: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[f"{row.get('query_id', '')}/{row.get('profile', '')}"].append(row)
        by_profile[row.get("profile", "")].append(row)
    groups = {key: _group_metrics(items, ks) for key, items in sorted(grouped.items())}
    groups.update(
        {
            f"overall/{profile}": _group_metrics(items, ks)
            for profile, items in sorted(by_profile.items())
        }
    )
    return {
        "quality_verdict": "PENDING HUMAN REVIEW"
        if any(not row.get("reviewer_label") for row in rows)
        else "REVIEWED LABELS AVAILABLE",
        "source_pack": str(path),
        "k_values": ks,
        "groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and score FODS retrieval review packs.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="Build a blank-label CSV from saved run logs.")
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--query-set", type=Path)
    collect.add_argument("runs", nargs="+", type=Path)
    score = subparsers.add_parser("score", help="Score only reviewer-provided CSV labels.")
    score.add_argument("--input", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--k", nargs="+", type=int, default=[5, 10])
    args = parser.parse_args()
    if args.command == "collect":
        try:
            rows = collect_review_pack(args.runs, args.output, args.query_set)
        except FileExistsError as exc:
            parser.error(str(exc))
        print(f"wrote {len(rows)} blank-label rows to {args.output}")
    else:
        report = score_review_pack(args.input, args.k)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {report['quality_verdict']} metrics to {args.output}")


if __name__ == "__main__":
    main()
